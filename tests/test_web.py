"""Cloudflare-versie: site/ actueel, en JS-logica gelijk aan de Python-logica."""

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.auto import suggest
from app.match import fingerprint
from tests.helpers import sample_image

ROOT = Path(__file__).resolve().parents[1]
node = shutil.which("node")


def test_site_is_up_to_date():
    r = subprocess.run([sys.executable, "tools/build_web.py", "--check"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_site_files_fit_cloudflare_pages():
    for f in (ROOT / "site").rglob("*"):
        if f.is_file():
            assert f.stat().st_size <= 25 * 1024 * 1024, f


def run_js(code):
    r = subprocess.run([node, "--input-type=module"], input=code, cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def rgba(img):
    a = np.asarray(img.convert("RGBA"), dtype=np.uint8)
    return a.ravel().tolist()


@pytest.mark.skipif(not node, reason="node niet geïnstalleerd")
def test_js_auto_and_fingerprint_match_python():
    imgs = [
        sample_image(160, 120, seed=1),
        Image.fromarray((np.asarray(sample_image(160, 120, seed=2)) * 0.3).astype(np.uint8)),
        sample_image(160, 120, seed=3).convert("L").convert("RGB"),
    ]
    data = json.dumps([rgba(i) for i in imgs])
    out = run_js(f"""
      import {{ suggest, fingerprint }} from "./web/js/analysis.js";
      const imgs = {data};
      console.log(JSON.stringify(imgs.map((a) => {{
        const px = Uint8ClampedArray.from(a);
        return {{ s: suggest(px), f: fingerprint(px) }};
      }})));
    """)
    for img, js in zip(imgs, out):
        py = suggest(img)
        assert js["s"]["state"]["preset"] == py["state"]["preset"]
        for k, v in py["state"]["adjust"].items():
            assert abs(js["s"]["state"]["adjust"].get(k, 0) - v) <= 1, k
        fp = fingerprint(np.asarray(img))
        assert np.allclose(js["f"]["lum"], fp["lum"], atol=0.01)
        assert np.allclose(js["f"]["tone"], fp["tone"], atol=0.005)


@pytest.mark.skipif(not node, reason="node niet geïnstalleerd")
def test_js_zip_is_valid(tmp_path):
    out = run_js("""
      import { makeZip } from "./web/js/zip.js";
      const files = [new File([new Uint8Array([1, 2, 3])], "a.jpg"), new File([new TextEncoder().encode("hallo")], "b é.jpg")];
      const blob = await makeZip(files);
      console.log(JSON.stringify(Array.from(new Uint8Array(await blob.arrayBuffer()))));
    """)
    p = tmp_path / "x.zip"
    p.write_bytes(bytes(out))
    z = zipfile.ZipFile(p)
    assert z.testzip() is None
    assert z.read("a.jpg") == bytes([1, 2, 3]) and z.read("b é.jpg") == b"hallo"
