"""End-to-end: upload -> auto -> upscale (echte Real-ESRGAN) -> export."""

import io
import time
import zipfile

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from tests.helpers import jpeg_bytes, sample_image, sharp_image


@pytest.fixture(scope="module")
def client():
    from app import auth

    auth.set_password("testwachtwoord")
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"password": "testwachtwoord"}).status_code == 200
        yield c


def upload(client, img, name="test.jpg"):
    if name.endswith(".png"):
        buf = io.BytesIO()
        img.save(buf, "PNG")
        data, mime = buf.getvalue(), "image/png"
    else:
        data, mime = jpeg_bytes(img), "image/jpeg"
    r = client.post("/api/photos", files=[("files", (name, data, mime))])
    assert r.status_code == 200, r.text
    return r.json()["photos"][0]


def wait_job(client, photo_id, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        p = next(x for x in client.get("/api/photos").json() if x["id"] == photo_id)
        if p["job"] and p["job"]["status"] in ("done", "error"):
            return p
        time.sleep(0.3)
    raise AssertionError("upscalen duurde te lang")


def test_upload_batch_and_invalid(client):
    files = [
        ("files", ("a.jpg", jpeg_bytes(sample_image(seed=1)), "image/jpeg")),
        ("files", ("b.jpg", jpeg_bytes(sample_image(seed=2)), "image/jpeg")),
        ("files", ("kapot.jpg", b"dit is geen foto", "image/jpeg")),
    ]
    r = client.post("/api/photos", files=files).json()
    assert len(r["photos"]) == 2 and len(r["errors"]) == 1
    p = r["photos"][0]
    assert client.get(p["preview_url"]).headers["content-type"] == "image/jpeg"


def test_auto_returns_valid_state(client):
    p = upload(client, sample_image())
    res = client.post(f"/api/photos/{p['id']}/auto").json()
    assert res["state"]["preset"] in {x["id"] for x in client.get("/api/presets").json()}


@pytest.mark.parametrize("factor", [2, 4])
def test_upscale_adds_resolution_and_detail(client, factor):
    hr = sharp_image(160 * factor, 120 * factor)
    src = hr.resize((160, 120), Image.BICUBIC)
    p = upload(client, src, "klein.png")
    r = client.post(f"/api/photos/{p['id']}/upscale", json={"factor": factor})
    assert r.status_code == 200
    done = wait_job(client, p["id"])
    assert done["job"]["status"] == "done", done["job"]
    assert (done["width"], done["height"]) == (160 * factor, 120 * factor)
    assert done["upscaled"] == factor

    # export van de ge-upscalede foto heeft de nieuwe resolutie
    exp = client.post("/api/export", json={"photo_ids": [p["id"]], "state": None}).json()
    data = client.get(exp["url"]).content
    out = Image.open(io.BytesIO(data))
    assert out.format == "JPEG" and out.size == (160 * factor, 120 * factor)

    # het AI-resultaat is scherper dan gewoon vergroten (bicubisch) en lijkt op het origineel
    big = np.asarray(out.convert("L"), dtype=float)
    bic = np.asarray(src.resize(out.size, Image.BICUBIC).convert("L"), dtype=float)
    ref = np.asarray(hr.convert("L"), dtype=float)
    grad = lambda a: np.abs(np.diff(a, axis=1)).mean()
    assert grad(big) > grad(bic) * 1.2
    assert np.corrcoef(big.ravel(), ref.ravel())[0, 1] > 0.9

    # terug naar origineel
    back = client.post(f"/api/photos/{p['id']}/reset-upscale").json()
    assert (back["width"], back["height"]) == (160, 120) and back["upscaled"] == 0


def test_export_applies_edits(client):
    p = upload(client, sample_image(seed=4))
    state = {"preset": "bw-contrast", "strength": 100, "adjust": {}}
    exp = client.post("/api/export", json={"photo_ids": [p["id"]], "state": state}).json()
    out = np.asarray(Image.open(io.BytesIO(client.get(exp["url"]).content)).convert("RGB"), dtype=int)
    assert np.abs(out[..., 0] - out[..., 2]).mean() < 3  # zwart-wit


def test_batch_export_zip_same_settings(client):
    ids = [upload(client, sample_image(seed=s), f"foto{s}.jpg")["id"] for s in (5, 6, 7)]
    state = {"preset": "film-warm", "strength": 80, "adjust": {"exposure": 10}}
    exp = client.post("/api/export", json={"photo_ids": ids, "state": state}).json()
    assert exp["count"] == 3 and exp["filename"].endswith(".zip")
    z = zipfile.ZipFile(io.BytesIO(client.get(exp["url"]).content))
    names = z.namelist()
    assert len(names) == 3 and all(n.endswith(".jpg") for n in names)
    for n in names:
        Image.open(io.BytesIO(z.read(n))).verify()


def test_state_and_custom_presets(client):
    p = upload(client, sample_image())
    st = {"preset": "cool-grey", "strength": 60, "adjust": {"grain": 20}}
    assert client.put(f"/api/photos/{p['id']}/state", json={"state": st}).json()["state"] == st
    new = client.post("/api/presets", json={"name": "Mijn Look", "params": {"exposure": 15, "fade": 30}}).json()
    assert new["short"] == "ML" and not new["builtin"]
    ids = [x["id"] for x in client.get("/api/presets").json()]
    assert new["id"] in ids
    assert client.delete(f"/api/presets/{new['id']}").status_code == 200
    assert client.delete("/api/presets/moody-dark").status_code == 404


def test_path_traversal_blocked(client):
    assert client.get("/api/exports/..%2F..%2Fpyproject.toml").status_code == 404
    assert client.get("/api/photos/../../etc/preview").status_code == 404
    assert client.get("/api/photos/zzzzzzzzzzzz/preview").status_code == 404


def test_ai_enhance_keeps_size(client):
    p = upload(client, sharp_image(200, 150), "scherp.png")
    client.post(f"/api/photos/{p['id']}/upscale", json={"factor": 1})
    done = wait_job(client, p["id"])
    assert done["job"]["status"] == "done"
    assert (done["width"], done["height"]) == (200, 150) and done["upscaled"] == 1
    exp = client.post("/api/export", json={"photo_ids": [p["id"]], "state": None}).json()
    assert exp["filename"].endswith("_ai_edit.jpg")


def test_copy_look_creates_preset(client):
    p = upload(client, sample_image(seed=8))
    ref = Image.fromarray((np.asarray(sample_image(seed=9)) * 0.35).astype(np.uint8))
    res = client.post(f"/api/photos/{p['id']}/match",
                      files=[("reference", ("voorbeeld.jpg", jpeg_bytes(ref), "image/jpeg"))]).json()
    assert res["preset"]["name"].startswith("Look ")
    assert res["preset"]["params"]["exposure"] < 0
    assert res["preset"]["id"] in {x["id"] for x in client.get("/api/presets").json()}
    bad = client.post(f"/api/photos/{p['id']}/match", files=[("reference", ("x.jpg", b"nee", "image/jpeg"))])
    assert bad.status_code == 400
