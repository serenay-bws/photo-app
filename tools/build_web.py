"""Bouw de Cloudflare-versie van de app in de map `site/`.

De Cloudflare-versie draait helemaal in de browser van je telefoon:
filters, Auto, Kopieer look en AI-upscaling (Real-ESRGAN via ONNX Runtime Web).
Cloudflare Pages serveert alleen deze bestanden; er draait geen server.

Gebruik:
    uv run python tools/build_web.py           # alles bouwen
    uv run python tools/build_web.py --check   # controleren of site/ actueel is (zonder vendor)
"""

import base64
import hashlib
import io
import json
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STATIC = ROOT / "app" / "static"
WEB = ROOT / "web"
SITE = ROOT / "site"
MODEL = ROOT / "app" / "models" / "realesr-general-x4v3.onnx"

ORT_VERSION = "1.30.0"
ORT_URL = f"https://registry.npmjs.org/onnxruntime-web/-/onnxruntime-web-{ORT_VERSION}.tgz"
ORT_SHA512 = "q0y+JrrtukXSzsBWEMccVfqX25LRmosXHF+CaRJmg8pZClzcV7svNc4rKY3jL02Vb7QmRMDs1SigqR4CXAfKYQ=="
ORT_FILES = ["ort.min.mjs", "ort-wasm-simd-threaded.jsep.mjs"]  # ort.min = WebGPU (JSEP) + WASM
ORT_WASM = "ort-wasm-simd-threaded.jsep.wasm"
PART_SIZE = 20 * 1024 * 1024  # Cloudflare Pages: max 25 MiB per bestand


def web_index():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html = html.replace('<script type="module" src="js/app.js"></script>',
                        '<script type="module" src="js/web-main.js"></script>')
    # manifest moet het inlog-cookie van Cloudflare Access meesturen
    html = html.replace('<link rel="manifest" href="manifest.webmanifest">',
                        '<link rel="manifest" href="manifest.webmanifest" crossorigin="use-credentials">')
    # geen "Telefoon"-knop: dit IS de telefoonversie
    html = html.replace('<button class="btn ghost" id="btn-phone"', '<button class="btn ghost" id="btn-phone" hidden')
    return html


def presets_json():
    from app.presets import BUILTIN

    return json.dumps([{k: p[k] for k in ("id", "name", "short", "params", "builtin")} for p in BUILTIN],
                      ensure_ascii=False, indent=1)


def generated_files():
    """Alle bestanden behalve de grote vendor-bestanden: pad -> bytes."""
    files = {}
    for f in STATIC.rglob("*"):
        if f.is_file():
            files[f.relative_to(STATIC).as_posix()] = f.read_bytes()
    for f in (WEB / "js").glob("*.js"):
        files[f"js/{f.name}"] = f.read_bytes()
    files["_headers"] = (WEB / "_headers").read_bytes()
    files["index.html"] = web_index().encode()
    files["presets.json"] = presets_json().encode()
    files["models/realesr-general-x4v3.onnx"] = MODEL.read_bytes()
    return files


def vendor_files():
    with urllib.request.urlopen(ORT_URL, timeout=120) as r:
        data = r.read()
    digest = base64.b64encode(hashlib.sha512(data).digest()).decode()
    if digest != ORT_SHA512:
        raise SystemExit("onnxruntime-web download klopt niet (checksum)")
    out = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        for name in ORT_FILES:
            out[f"vendor/ort/{name}"] = t.extractfile(f"package/dist/{name}").read()
        wasm = t.extractfile(f"package/dist/{ORT_WASM}").read()
    parts = [wasm[i : i + PART_SIZE] for i in range(0, len(wasm), PART_SIZE)]
    if len(parts) != 2:
        raise SystemExit(f"verwachtte 2 wasm-delen, kreeg {len(parts)} (pas webai.js aan)")
    for i, p in enumerate(parts):
        out[f"vendor/ort/{ORT_WASM}.part{i}"] = p
    return out


def check():
    stale = []
    for path, data in generated_files().items():
        f = SITE / path
        if not f.exists() or f.read_bytes() != data:
            stale.append(path)
    return stale


def build():
    files = generated_files()
    keep_vendor = (SITE / "vendor").exists()
    vendor = {} if keep_vendor else vendor_files()
    for child in SITE.glob("*") if SITE.exists() else []:
        if child.name == "vendor":
            continue
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    for path, data in {**files, **vendor}.items():
        f = SITE / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    big = [f for f in SITE.rglob("*") if f.is_file() and f.stat().st_size > 25 * 1024 * 1024]
    if big:
        raise SystemExit(f"te groot voor Cloudflare Pages: {big}")
    print(f"site/ gebouwd: {sum(1 for f in SITE.rglob('*') if f.is_file())} bestanden")


if __name__ == "__main__":
    if "--check" in sys.argv:
        stale = check()
        print("verouderd: " + ", ".join(stale) if stale else "site/ is actueel")
        sys.exit(1 if stale else 0)
    build()
