"""Beeldbewerking (de "filters").

Dezelfde formules staan ook in app/static/js/renderer.js (WebGL), zodat de
live-preview in de browser er hetzelfde uitziet als de geëxporteerde JPG.
Pas je hier iets aan, doe dat daar dan ook.

Volgorde per pixel (waarden 0..1, sRGB):
  1. verscherpen (unsharp mask, 3x3)
  2. witbalans + belichting (in lineair licht)
  3. contrast
  4. hoge lichten / schaduwen
  5. zwarten
  6. verzadiging
  7. split toning (kleur in schaduwen / hoge lichten)
  8. fade (matte look)
  9. vignet
 10. filmkorrel
Tussen 6 en 7 zit nog "kleurtinten" (HSL): verzadiging/helderheid per kleurgebied
(huid/oranje, groen, blauw).
"""

import numpy as np

# Schuifregelaars: naam -> (min, max)
SLIDERS = {
    "exposure": (-100, 100),
    "contrast": (-100, 100),
    "highlights": (-100, 100),
    "shadows": (-100, 100),
    "blacks": (-100, 100),
    "saturation": (-100, 100),
    "temperature": (-100, 100),
    "tint": (-100, 100),
    "grain": (0, 100),
    "vignette": (0, 100),
    "sharpness": (0, 100),
    "fade": (0, 100),
}
# Extra instellingen die presets gebruiken (kleurtint in schaduwen/lichten)
TONING = {
    "split_shadow": (0, 100),
    "split_highlight": (0, 100),
}
# Kleurtinten (HSL): naam -> (min, max); werkt alleen op dat kleurgebied
HSL = {
    "orange_sat": (-100, 100),
    "orange_lum": (-100, 100),
    "green_sat": (-100, 100),
    "blue_sat": (-100, 100),
}
# kleurgebied: (middelste tint in graden, halve breedte)
HSL_RANGES = {"orange": (30.0, 35.0), "green": (110.0, 50.0), "blue": (215.0, 50.0)}
HUES = ("split_shadow_hue", "split_highlight_hue")
SCALABLE = {**SLIDERS, **HSL, **TONING}
PARAM_KEYS = list(SCALABLE) + list(HUES)

# Korrel en verscherping zijn gedefinieerd op een raster van max. GRID_LONG
# cellen over de lange zijde, zodat preview en export er gelijk uitzien.
GRID_LONG = 1600
STRIP_ROWS = 256


def default_params():
    p = {k: 0.0 for k in SCALABLE}
    p["split_shadow_hue"] = 210.0
    p["split_highlight_hue"] = 40.0
    return p


def _num(v, default=0.0):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return v if np.isfinite(v) else default


def clean_params(raw):
    """Maak een geldige, volledige set parameters van willekeurige invoer."""
    p = default_params()
    raw = raw or {}
    for k, (lo, hi) in SCALABLE.items():
        p[k] = float(np.clip(_num(raw.get(k), 0.0), lo, hi))
    for k in HUES:
        p[k] = _num(raw.get(k), p[k]) % 360.0
    return p


def effective_params(state, presets):
    """state = {"preset": id of None, "strength": 0..100, "adjust": {...}}

    Resultaat = preset * sterkte + eigen aanpassingen (zoals VSCO)."""
    state = state or {}
    adjust = state.get("adjust") or {}
    preset = presets.get(state.get("preset") or "") if state.get("preset") else None
    base = clean_params(preset["params"]) if preset else default_params()
    strength = float(np.clip(_num(state.get("strength"), 100.0), 0, 100)) / 100.0
    out = {}
    for k, (lo, hi) in SCALABLE.items():
        b = base[k] * strength if preset else 0.0
        out[k] = float(np.clip(b + _num(adjust.get(k), 0.0), lo, hi))
    for k in HUES:
        amount_key = k[: -len("_hue")]
        if preset and base[amount_key] > 0:
            out[k] = base[k]
        else:
            out[k] = _num(adjust.get(k), base[k]) % 360.0
    return out


def is_identity(p):
    return all(abs(p[k]) < 1e-6 for k in SCALABLE)


def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _luma(c):
    return c[..., 0] * 0.2126 + c[..., 1] * 0.7152 + c[..., 2] * 0.0722


def _hue_rgb(h):
    h = (h % 360.0) / 360.0
    return np.array(
        [
            np.clip(abs(h * 6 - 3) - 1, 0, 1),
            np.clip(2 - abs(h * 6 - 2), 0, 1),
            np.clip(2 - abs(h * 6 - 4), 0, 1),
        ],
        dtype=np.float32,
    )


def _hue_weights(c):
    """Tint (graden) per pixel en een weging die grijze pixels negeert."""
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    chroma = mx - mn
    safe = np.maximum(chroma, 1e-6)
    h = np.where(
        mx == r, np.mod((g - b) / safe, 6.0),
        np.where(mx == g, (b - r) / safe + 2.0, (r - g) / safe + 4.0),
    ) * 60.0
    return h, _smoothstep(0.02, 0.15, chroma)


def _range_weight(h, center, half):
    d = np.abs(np.mod(h - center + 180.0, 360.0) - 180.0)
    return np.clip(1.0 - d / half, 0.0, 1.0)


def _hsl_adjust(c, p):
    h, chroma_w = _hue_weights(c)
    w_o = _range_weight(h, *HSL_RANGES["orange"]) * chroma_w
    w_g = _range_weight(h, *HSL_RANGES["green"]) * chroma_w
    w_b = _range_weight(h, *HSL_RANGES["blue"]) * chroma_w
    sat = 1.0 + (w_o * p["orange_sat"] + w_g * p["green_sat"] + w_b * p["blue_sat"]) / 100.0
    lum = 1.0 + w_o * (p["orange_lum"] / 100.0 * 0.6)
    L = _luma(c)[..., None]
    c = L + (c - L) * sat[..., None]
    return c * lum[..., None]


class _Geometry:
    """Afmetingen + korrel-raster voor één volledige afbeelding."""

    def __init__(self, width, height, seed=7):
        self.w, self.h = width, height
        self.long = max(width, height)
        self.grid_long = min(GRID_LONG, self.long)
        self.radius = max(1, int(round(self.long / self.grid_long)))
        self.cell = self.long / self.grid_long  # pixels per rastercel
        gw = int(np.ceil(width / self.cell)) + 2
        gh = int(np.ceil(height / self.cell)) + 2
        self.noise = np.random.default_rng(seed).random((gh, gw), dtype=np.float32)


def _grain_noise(geo, y0, y1):
    gy = (np.arange(y0, y1, dtype=np.float32) + 0.5) / geo.cell
    gx = (np.arange(geo.w, dtype=np.float32) + 0.5) / geo.cell
    iy, ix = np.floor(gy).astype(np.int64), np.floor(gx).astype(np.int64)
    fy, fx = (gy - iy)[:, None], (gx - ix)[None, :]
    n = geo.noise
    a = n[iy][:, ix]
    b = n[iy][:, ix + 1]
    c = n[iy + 1][:, ix]
    d = n[iy + 1][:, ix + 1]
    top = a + (b - a) * fx
    bot = c + (d - c) * fx
    return top + (bot - top) * fy - 0.5


def _process_rows(src, y0, y1, p, geo):
    """Bewerk rijen y0..y1 van `src` (uint8 HxWx3); geeft float32 terug."""
    h = geo.h
    r = geo.radius if p["sharpness"] > 0 else 0
    rows = np.clip(np.arange(y0 - r, y1 + r), 0, h - 1)
    block = src[rows].astype(np.float32) / 255.0

    # 1. verscherpen
    if r:
        padded = np.pad(block, ((0, 0), (r, r), (0, 0)), mode="edge")
        w = geo.w

        def shift(dy, dx):
            return padded[r + dy : r + dy + (y1 - y0), r + dx : r + dx + w]

        blur = (
            shift(-r, -r) + shift(-r, r) + shift(r, -r) + shift(r, r)
            + 2 * (shift(-r, 0) + shift(r, 0) + shift(0, -r) + shift(0, r))
            + 4 * shift(0, 0)
        ) / 16.0
        c = shift(0, 0) + (shift(0, 0) - blur) * (p["sharpness"] / 100.0 * 2.0)
    else:
        c = block

    # 2. witbalans + belichting in lineair licht
    t, g = p["temperature"] / 100.0, p["tint"] / 100.0
    exp = 2.0 ** (p["exposure"] / 100.0 * 2.0)
    if t or g or p["exposure"]:
        lin = np.power(np.maximum(c, 0.0), 2.2)
        gain = np.array([1 + 0.25 * t, 1 - 0.2 * g, 1 - 0.25 * t], np.float32) * exp
        c = np.power(np.maximum(lin * gain, 0.0), 1 / 2.2)

    # 3. contrast
    if p["contrast"]:
        c = 0.5 + (c - 0.5) * (1.0 + p["contrast"] / 100.0)

    # 4. hoge lichten / schaduwen
    if p["highlights"] or p["shadows"]:
        L = _luma(c)
        delta = (p["highlights"] / 100.0 * 0.35) * _smoothstep(0.45, 1.0, L) + (
            p["shadows"] / 100.0 * 0.35
        ) * (1.0 - _smoothstep(0.0, 0.55, L))
        c = c + delta[..., None]

    # 5. zwarten
    if p["blacks"]:
        bp = -p["blacks"] / 100.0 * 0.12
        c = (c - bp) / (1.0 - bp)

    # 6. verzadiging
    if p["saturation"]:
        L = _luma(c)[..., None]
        c = L + (c - L) * (1.0 + p["saturation"] / 100.0)

    # 6b. kleurtinten (HSL)
    if p["orange_sat"] or p["orange_lum"] or p["green_sat"] or p["blue_sat"]:
        c = _hsl_adjust(c, p)

    # 7. split toning
    if p["split_shadow"] or p["split_highlight"]:
        L = np.clip(_luma(c), 0, 1)[..., None]
        sh = (_hue_rgb(p["split_shadow_hue"]) - 0.5) * (p["split_shadow"] / 100.0 * 0.3)
        hi = (_hue_rgb(p["split_highlight_hue"]) - 0.5) * (p["split_highlight"] / 100.0 * 0.3)
        c = c + sh * (1 - L) ** 2 + hi * L**2

    # 8. fade
    if p["fade"]:
        f = p["fade"] / 100.0
        lo, hi = 0.2 * f, 1.0 - 0.05 * f
        c = lo + c * (hi - lo)

    # 9. vignet
    if p["vignette"]:
        long = float(geo.long)
        nx = (np.arange(geo.w, dtype=np.float32) + 0.5) / geo.w * 2 - 1
        ny = (np.arange(y0, y1, dtype=np.float32) + 0.5) / geo.h * 2 - 1
        ax, ay = geo.w / long, geo.h / long
        dist = np.sqrt((nx[None, :] * ax) ** 2 + (ny[:, None] * ay) ** 2) / np.hypot(ax, ay)
        c = c * (1.0 - p["vignette"] / 100.0 * 0.7 * _smoothstep(0.3, 1.05, dist))[..., None]

    # 10. filmkorrel
    if p["grain"]:
        L = np.clip(_luma(c), 0, 1)
        weight = 1.0 - 0.6 * (2 * L - 1) ** 2
        c = c + (_grain_noise(geo, y0, y1) * weight * (p["grain"] / 100.0 * 0.25))[..., None]

    return np.clip(c, 0.0, 1.0)


def apply_edits(img, params):
    """Pas parameters toe op een uint8 RGB-array (H x W x 3). Werkt in stroken,
    zodat ook zeer grote (ge-upscalede) foto's weinig geheugen kosten."""
    p = clean_params(params)
    if is_identity(p):
        return img
    h, w = img.shape[:2]
    geo = _Geometry(w, h)
    out = np.empty_like(img)
    # vaste dither-tegel: voorkomt kleurstreepjes (banding) in donkere verlopen
    dither = np.random.default_rng(11).random((64, 64), dtype=np.float32)
    reps = (-(-w // 64))
    for y0 in range(0, h, STRIP_ROWS):
        y1 = min(h, y0 + STRIP_ROWS)
        rows = np.arange(y0, y1) % 64
        d = np.tile(dither[rows], (1, reps))[:, :w, None]
        out[y0:y1] = (_process_rows(img, y0, y1, p, geo) * 255.0 + d).astype(np.uint8)
    return out
