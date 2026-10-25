import numpy as np
from PIL import Image

from app.auto import suggest
from tests.helpers import sample_image


def test_dark_photo_gets_brightened_and_moody():
    dark = Image.fromarray((np.asarray(sample_image()) * 0.25).astype(np.uint8))
    res = suggest(dark)
    assert res["state"]["preset"] == "moody-dark"
    assert res["state"]["adjust"].get("exposure", 0) > 0


def test_greyscale_photo_gets_bw():
    grey = sample_image().convert("L").convert("RGB")
    assert suggest(grey)["state"]["preset"] == "bw-contrast"


def test_bright_photo_gets_clean_bright():
    a = np.asarray(sample_image()).astype(float)
    bright = Image.fromarray(np.clip(a * 0.35 + 165, 0, 255).astype(np.uint8))
    assert suggest(bright)["state"]["preset"] == "clean-bright"


def test_warm_photo_detected():
    a = np.asarray(sample_image()).astype(float)
    a[..., 0] = np.clip(a[..., 0] * 1.35 + 20, 0, 255)
    a[..., 2] *= 0.6
    res = suggest(Image.fromarray(a.astype(np.uint8)))
    assert res["stats"]["warmth"] > 0.12
    assert res["summary"]
