"""Bijsnijden, draaien en rechtzetten (export). Zelfde regels als app/static/js/geometry.js."""

import math

from PIL import Image


def _num(v, d):
    try:
        v = float(v)
        return v if math.isfinite(v) else d
    except (TypeError, ValueError):
        return d


def clean_crop(g):
    if not isinstance(g, dict):
        return None
    aspect = g.get("aspect")
    aspect = _num(aspect, 0) or None
    return {
        "rot": int(_num(g.get("rot"), 0)) % 4,
        "angle": max(-45.0, min(45.0, _num(g.get("angle"), 0))),
        "aspect": max(0.1, min(10.0, aspect)) if aspect else None,
        "zoom": max(0.2, min(1.0, _num(g.get("zoom"), 1))),
        "cx": max(0.0, min(1.0, _num(g.get("cx"), 0.5))),
        "cy": max(0.0, min(1.0, _num(g.get("cy"), 0.5))),
    }


def is_identity(g):
    return g is None or (g["rot"] == 0 and g["angle"] == 0 and not g["aspect"] and g["zoom"] >= 1)


def frame_size(w, h, g):
    return (h, w) if g["rot"] % 2 else (w, h)


def fill_scale(fw, fh, angle):
    a = abs(math.radians(angle))
    c, s = math.cos(a), math.sin(a)
    return max((fw * c + fh * s) / fw, (fw * s + fh * c) / fh)


def crop_rect(w, h, g):
    fw, fh = frame_size(w, h, g)
    A = g["aspect"] or fw / fh
    max_w = min(fw, fh * A)
    cw, ch = max_w * g["zoom"], max_w / A * g["zoom"]
    x = min(max(g["cx"] * fw - cw / 2, 0), fw - cw)
    y = min(max(g["cy"] * fh - ch / 2, 0), fh - ch)
    return x, y, cw, ch


def apply_geometry(img, crop):
    """Pas draaien/rechtzetten/bijsnijden toe op een PIL-afbeelding (volle resolutie)."""
    g = clean_crop(crop)
    if is_identity(g):
        return img
    x, y, cw, ch = crop_rect(img.width, img.height, g)
    rot = {1: Image.Transpose.ROTATE_270, 2: Image.Transpose.ROTATE_180, 3: Image.Transpose.ROTATE_90}
    if g["rot"]:
        img = img.transpose(rot[g["rot"]])
    fw, fh = img.size
    out_w, out_h = max(1, round(cw)), max(1, round(ch))
    if not g["angle"]:
        return img.crop((round(x), round(y), round(x) + out_w, round(y) + out_h))
    # uitvoerpixel -> bronpixel: q = c + R(-a) (p - c) / k
    k = fill_scale(fw, fh, g["angle"])
    a = math.radians(g["angle"])
    ca, sa = math.cos(a), math.sin(a)
    cx, cy = fw / 2, fh / 2
    data = (
        ca / k, sa / k, cx + (ca * (x - cx) + sa * (y - cy)) / k,
        -sa / k, ca / k, cy + (-sa * (x - cx) + ca * (y - cy)) / k,
    )
    return img.transform((out_w, out_h), Image.Transform.AFFINE, data, resample=Image.Resampling.BICUBIC)
