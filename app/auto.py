"""Auto-knop: analyseer het histogram en kies preset + correcties."""

import numpy as np

from .imaging import resized


def analyze(img):
    """Statistieken van een PIL-afbeelding (op verkleinde versie)."""
    a = np.asarray(resized(img, 512).convert("RGB"), dtype=np.float32) / 255.0
    lum = a @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = np.where(mx > 1e-3, (mx - mn) / np.maximum(mx, 1e-3), 0.0)
    # kleurzweem bepalen op middentonen (geen uitgebrande/zwarte pixels)
    mid = (lum > 0.15) & (lum < 0.85)
    sample = a[mid] if mid.sum() > 100 else a.reshape(-1, 3)
    r, g, b = sample.mean(axis=0)
    hist = np.histogram(lum, bins=32, range=(0, 1))[0] / lum.size
    return {
        "mean": float(lum.mean()),
        "median": float(np.median(lum)),
        "std": float(lum.std()),
        "p2": float(np.percentile(lum, 2)),
        "p98": float(np.percentile(lum, 98)),
        "clip_low": float((lum < 0.02).mean()),
        "clip_high": float((lum > 0.98).mean()),
        "saturation": float(sat.mean()),
        "warmth": float((r - b) / max((r + g + b) / 3, 1e-3)),
        "green_magenta": float((g - (r + b) / 2) / max((r + g + b) / 3, 1e-3)),
        "histogram": [round(float(x), 4) for x in hist],
    }


def suggest(img):
    s = analyze(img)
    mean, std, sat, warmth = s["mean"], s["std"], s["saturation"], s["warmth"]

    if sat < 0.08:
        preset, why = "bw-contrast", "weinig kleur in de foto"
    elif mean < 0.32:
        preset, why = "moody-dark", "donkere, low-key foto"
    elif mean > 0.58 and std < 0.26:
        preset, why = "clean-bright", "lichte, luchtige foto"
    elif warmth > 0.12:
        preset, why = "film-warm", "warme tinten"
    elif warmth < -0.08:
        preset, why = "cool-grey", "koele tinten"
    elif sat > 0.35:
        preset, why = "film-warm", "veel kleur, past goed bij film"
    elif std < 0.17:
        preset, why = "clean-bright", "zacht licht met weinig contrast"
    else:
        preset, why = "moody-dark", "uitgebalanceerde foto, geschikt voor een moody look"

    adjust = {}
    notes = []

    # Belichting: streef naar een middentoon die past bij de preset
    target = {"moody-dark": 0.36, "clean-bright": 0.52, "bw-contrast": 0.45}.get(preset, 0.46)
    m = max(s["median"], 0.02)
    stops = 2.2 * np.log2(target / m) * 0.6  # 60% corrigeren, preset doet de rest
    exposure = float(np.clip(stops * 50, -45, 45))
    if abs(exposure) >= 4:
        adjust["exposure"] = round(exposure)
        notes.append("lichter gemaakt" if exposure > 0 else "donkerder gemaakt")

    # Contrast
    if std < 0.16:
        adjust["contrast"] = round(min(30, (0.2 - std) * 250))
        notes.append("meer contrast")
    elif std > 0.3:
        adjust["contrast"] = -round(min(25, (std - 0.28) * 200))
        notes.append("minder contrast")

    # Uitgebrande lichten / dichtgelopen schaduwen terughalen
    if s["clip_high"] > 0.02:
        adjust["highlights"] = -round(min(40, s["clip_high"] * 400))
        notes.append("hoge lichten hersteld")
    if s["clip_low"] > 0.05 and preset not in ("moody-dark", "bw-contrast"):
        adjust["shadows"] = round(min(35, s["clip_low"] * 200))
        notes.append("schaduwen opgehaald")
    if s["p2"] > 0.1:
        adjust["blacks"] = -round(min(30, (s["p2"] - 0.05) * 150))
        notes.append("diepere zwarten")

    # Kleurzweem half neutraliseren (behalve als de preset de tint juist wil)
    if preset != "bw-contrast":
        if abs(warmth) > 0.06 and preset not in ("film-warm", "cool-grey"):
            adjust["temperature"] = round(float(np.clip(-warmth * 120, -30, 30)))
            notes.append("witbalans gecorrigeerd")
        # alleen een groenzweem corrigeren (bv. tl-licht); rood/oranje is meestal gewoon het onderwerp
        gm = s["green_magenta"]
        if gm > 0.06:
            adjust["tint"] = round(float(min(gm * 120, 20)))

    strength = 80 if preset in ("moody-dark", "film-warm") else 75
    names = {
        "moody-dark": "Moody Dark",
        "clean-bright": "Clean Bright",
        "film-warm": "Film Warm",
        "cool-grey": "Cool Grey",
        "bw-contrast": "B&W Contrast",
    }
    summary = f"{names[preset]} — {why}"
    if notes:
        summary += "; " + ", ".join(notes)
    return {
        "state": {"preset": preset, "strength": strength, "adjust": adjust},
        "summary": summary,
        "stats": s,
    }
