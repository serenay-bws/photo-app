import io

import numpy as np
from PIL import Image

from app.geometry import apply_geometry, crop_rect, clean_crop
from tests.test_api import client, upload  # noqa: F401  (fixture hergebruiken)
from tests.helpers import sample_image


def quad():
    im = Image.new("RGB", (400, 300), (255, 0, 0))
    im.paste((0, 0, 255), (0, 0, 200, 150))  # blauw linksboven
    return im


def test_identity_is_untouched():
    im = quad()
    assert apply_geometry(im, None) is im
    assert apply_geometry(im, {"rot": 0, "angle": 0, "aspect": None, "zoom": 1}) is im


def test_rotate_quarter_clockwise():
    out = apply_geometry(quad(), {"rot": 1})
    assert out.size == (300, 400)
    assert out.getpixel((290, 10)) == (0, 0, 255)   # blauw nu rechtsboven
    assert out.getpixel((10, 10)) == (255, 0, 0)


def test_aspect_zoom_and_position():
    out = apply_geometry(quad(), {"aspect": 1, "zoom": 0.5, "cx": 0.0, "cy": 0.0})
    assert out.size == (150, 150)
    assert np.all(np.asarray(out)[..., 2] == 255)    # helemaal in het blauwe vlak


def test_straighten_has_no_empty_corners():
    out = apply_geometry(quad(), {"angle": 12})
    a = np.asarray(out)
    assert out.size == (400, 300)
    assert a.sum(axis=2).min() > 0                    # geen zwarte (lege) hoeken


def test_crop_rect_stays_inside():
    g = clean_crop({"aspect": 9 / 16, "zoom": 0.6, "cx": 1.0, "cy": 0.0})
    x, y, w, h = crop_rect(4000, 3000, g)
    assert x + w <= 4000 + 1e-6 and y >= 0 and abs(w / h - 9 / 16) < 1e-6


def test_export_uses_photo_crop(client):  # noqa: F811
    p = upload(client, sample_image(320, 240, seed=12))
    state = {"preset": None, "strength": 100, "adjust": {}, "crop": {"aspect": 1, "zoom": 1, "cx": 0.5, "cy": 0.5}}
    client.put(f"/api/photos/{p['id']}/state", json={"state": state})
    # "alle foto's met deze instellingen": look van een andere foto, eigen uitsnede blijft
    exp = client.post("/api/export", json={"photo_ids": [p["id"]], "state": {"preset": "bw-contrast", "adjust": {}}}).json()
    out = Image.open(io.BytesIO(client.get(exp["url"]).content))
    assert out.size == (240, 240)
