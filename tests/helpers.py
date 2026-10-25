import io

import numpy as np
from PIL import Image, ImageDraw


def sample_image(w=320, h=240, seed=0):
    """Synthetische 'foto': verloop + vormen + ruis, zodat er detail in zit."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    r = 0.5 + 0.4 * np.sin(x / 17.0) * np.cos(y / 23.0)
    g = (x / w) * 0.8 + 0.1
    b = (y / h) * 0.7 + 0.15
    img = np.stack([r, g, b], axis=-1)
    img[(x - w * 0.6) ** 2 + (y - h * 0.4) ** 2 < (h * 0.2) ** 2] = [0.9, 0.85, 0.7]
    img += rng.normal(0, 0.02, img.shape)
    return Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))


def jpeg_bytes(img, quality=92):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def sharp_image(w=640, h=480):
    """Scherpe vormen en tekst: goed om echte detailwinst van upscaling te meten."""
    img = Image.new("RGB", (w, h), (200, 190, 170))
    d = ImageDraw.Draw(img)
    for i in range(12):
        d.ellipse((20 + i * 50, 40, 60 + i * 50, 80 + i * 8), fill=(30 + i * 15, 60, 120))
    for i in range(8):
        d.rectangle((30 + i * 75, 250, 70 + i * 75, 420), fill=(20, 20, 20) if i % 2 else (240, 240, 240))
    d.text((40, 150), "FOTOSTUDIO REAL-ESRGAN TEST 1234567890", fill=(10, 10, 10))
    return img
