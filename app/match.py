"""Kopieer look: zoek instellingen die jouw foto dezelfde sfeer geven als een voorbeeldfoto.

We vergelijken 'vingerafdrukken' van beide foto's: de verdeling van licht en donker,
hoe kleurrijk de foto is, welke kleurtint de schaduwen/middentonen/hoge lichten
hebben en hoe de huidtinten, groenen en blauwen eruitzien. Daarna zoeken we de
schuifregelaar-standen waarmee jouw foto dezelfde vingerafdruk krijgt.
"""

import numpy as np

from .edits import HSL_RANGES, _hue_weights, _luma, _range_weight, apply_edits, clean_params
from .imaging import resized

QUANTILES = np.array([0.02, 0.1, 0.25, 0.5, 0.75, 0.9, 0.98])
KEYS = ["exposure", "contrast", "highlights", "shadows", "blacks", "fade", "saturation",
        "temperature", "tint", "orange_sat", "orange_lum", "green_sat", "blue_sat"]
SPLIT = ["split_shadow", "split_highlight"]
LUM_W, CHROMA_W, TONE_W, REG = 2.0, 3.0, 6.0, 1e-3


def fingerprint(arr):
    """arr: uint8 HxWx3. Geeft dict met kenmerken."""
    c = arr.astype(np.float32) / 255.0
    L = _luma(c)
    h, cw = _hue_weights(c)
    chroma = c.max(axis=2) - c.min(axis=2)
    a = c[..., 0] - c[..., 1]                      # rood <-> groen
    yb = (c[..., 0] + c[..., 1]) / 2 - c[..., 2]   # geel <-> blauw
    bands = {"shadow": (1 - L) ** 2, "mid": 1 - np.abs(2 * L - 1), "high": L**2}
    fp = {
        "lum": np.quantile(L, QUANTILES),
        "chroma": np.array([chroma.mean(), np.quantile(chroma, 0.8)]),
        "tone": np.array([
            v for w in bands.values() for v in ((a * w).sum() / w.sum(), (yb * w).sum() / w.sum())
        ]),
    }
    for name, (center, half) in HSL_RANGES.items():
        w = _range_weight(h, center, half) * cw
        share = float(w.mean())
        if share > 0.01:
            fp[name] = (share, np.array([(L * w).sum() / w.sum(), (chroma * w).sum() / w.sum()]))
    return fp


def _distance(fp, ref):
    d = LUM_W * np.sum((fp["lum"] - ref["lum"]) ** 2)
    d += CHROMA_W * np.sum((fp["chroma"] - ref["chroma"]) ** 2)
    d += TONE_W * np.sum((fp["tone"] - ref["tone"]) ** 2)
    for name in HSL_RANGES:
        if name in fp and name in ref:
            weight = 2.0 * min(1.0, 10 * min(fp[name][0], ref[name][0]))
            diff = fp[name][1] - ref[name][1]
            if name != "orange":
                diff = diff[1:]  # alleen bij huid ook de helderheid
            d += weight * np.sum(diff**2)
    return d


def _params(x):
    p = {k: float(v) * 100 for k, v in zip(KEYS, x[: len(KEYS)])}
    for i, name in enumerate(SPLIT):
        sx, sy = x[len(KEYS) + 2 * i : len(KEYS) + 2 * i + 2]
        p[name] = float(np.hypot(sx, sy)) * 100
        p[name + "_hue"] = float(np.degrees(np.arctan2(sy, sx)) % 360)
    return clean_params(p)


def match_look(photo_img, reference_img, max_evals=900):
    """Geeft (params, score_voor, score_na)."""
    src = np.asarray(resized(photo_img, 200).convert("RGB"))
    ref = fingerprint(np.asarray(resized(reference_img, 300).convert("RGB")))
    reg = REG

    def cost(x):
        return _distance(fingerprint(apply_edits(src, _params(x))), ref) + reg * float(np.sum(x * x))

    x = np.zeros(len(KEYS) + 2 * len(SPLIT))
    best = cost(x)
    start = best
    evals = 0
    for step in (0.4, 0.2, 0.1, 0.05, 0.02):
        improved = True
        while improved and evals < max_evals:
            improved = False
            for i in range(len(x)):
                for sign in (1, -1):
                    trial = x.copy()
                    trial[i] = np.clip(trial[i] + sign * step, -1, 1)
                    c = cost(trial)
                    evals += 1
                    if c < best - 1e-7:
                        x, best, improved = trial, c, True
                        break
    return _params(x), start, best


def describe(params):
    """Korte uitleg in gewone taal."""
    p = params
    words = []
    if p["exposure"] <= -15:
        words.append("donkerder")
    elif p["exposure"] >= 15:
        words.append("lichter")
    if p["contrast"] >= 15:
        words.append("meer contrast")
    elif p["contrast"] <= -15:
        words.append("zachter contrast")
    if p["saturation"] <= -20:
        words.append("gedempte kleuren")
    elif p["saturation"] >= 20:
        words.append("kleurrijker")
    if p["temperature"] >= 12:
        words.append("warmer")
    elif p["temperature"] <= -12:
        words.append("koeler")
    if p["fade"] >= 15:
        words.append("matte zwarten")
    if abs(p["orange_lum"]) >= 15 or abs(p["orange_sat"]) >= 15:
        words.append("huidtinten aangepast")
    return ", ".join(words) or "subtiele aanpassing"
