"""Foto's openen en opslaan (incl. iPhone HEIC en EXIF-rotatie)."""

import io

import numpy as np
from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # pragma: no cover - HEIC is optioneel
    pass

Image.MAX_IMAGE_PIXELS = 400_000_000


def open_rgb(path_or_bytes):
    """Open een afbeelding als RGB, rechtgezet volgens EXIF. Geeft (img, icc)."""
    src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, bytes) else path_or_bytes
    img = Image.open(src)
    icc = img.info.get("icc_profile")
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.getchannel("A"))
        img = bg
    elif img.mode in ("I;16", "I;16B", "I;16L", "I"):
        arr = np.asarray(img, dtype=np.float32)
        img = Image.fromarray((arr / max(arr.max(), 1) * 255).astype(np.uint8)).convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")
    return img, icc


def resized(img, long_side):
    w, h = img.size
    scale = long_side / max(w, h)
    if scale >= 1:
        return img.copy()
    return img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)


def save_jpeg(img, path, quality, icc=None):
    kwargs = {"quality": quality, "subsampling": 0 if quality >= 90 else 2, "optimize": img.width * img.height < 20_000_000}
    if icc:
        kwargs["icc_profile"] = icc
    img.save(path, "JPEG", **kwargs)
