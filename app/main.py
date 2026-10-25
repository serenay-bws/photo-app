"""Webserver (FastAPI). Alles draait lokaal op deze computer."""

import io
import logging
import os
import re
import socket
import subprocess
import sys
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

from . import auto, presets, store
from .config import DATA_DIR, EXPORTS_DIR, JPEG_QUALITY, STATIC_DIR
from .edits import apply_edits, effective_params
from .imaging import open_rgb, save_jpeg
from .upscaler import target_size, upscaler

log = logging.getLogger("fotostudio")


def _export_dir():
    pictures = Path.home() / "Pictures"
    if pictures.is_dir():
        d = pictures / "Fotostudio"
        try:
            d.mkdir(exist_ok=True)
            return d
        except OSError:
            pass
    return EXPORTS_DIR


EXPORT_DIR = _export_dir()

@asynccontextmanager
async def _lifespan(_app):
    upscaler.start()
    yield


app = FastAPI(title="Fotostudio", lifespan=_lifespan)


@app.exception_handler(store.PhotoNotFound)
def _not_found(_request, _exc):
    return JSONResponse({"detail": "Foto niet gevonden"}, status_code=404)


# ------------------------------------------------------------------ helpers


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # er wordt niets verstuurd
            return s.getsockname()[0]
    except OSError:
        return None


def _photo_json(meta):
    job = upscaler.job_for_photo(meta["id"])
    out = dict(meta)
    v = meta.get("version", 1)
    out["preview_url"] = f"/api/photos/{meta['id']}/preview?v={v}"
    out["thumb_url"] = f"/api/photos/{meta['id']}/thumb?v={v}"
    out["targets"] = {
        str(f): target_size(meta["orig_width"], meta["orig_height"], f) for f in (2, 4)
    }
    out["job"] = (
        {k: job.get(k) for k in ("id", "status", "progress", "message", "eta", "factor")}
        if job else None
    )
    return out


def _safe_name(name):
    stem = Path(name or "foto").stem
    stem = re.sub(r"[^\w\-]+", "_", stem).strip("_") or "foto"
    return stem[:60]


def _is_local(request: Request):
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost")


# --------------------------------------------------------------------- API


@app.get("/api/status")
def status(request: Request):
    port = request.url.port or 80
    ip = lan_ip()
    return {
        "upscaler": upscaler.info(),
        "lan_url": f"http://{ip}:{port}" if ip else None,
        "export_dir": str(EXPORT_DIR),
        "is_local": _is_local(request),
    }


@app.get("/api/qr")
def qr(request: Request):
    import qrcode
    import qrcode.image.svg

    ip = lan_ip()
    url = f"http://{ip}:{request.url.port or 80}" if ip else str(request.base_url)
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml")


@app.get("/api/photos")
def photos():
    return [_photo_json(m) for m in store.list_photos()]


@app.post("/api/photos")
async def upload(files: list[UploadFile] = File(...)):
    created, errors = [], []
    for f in files:
        data = await f.read()
        try:
            meta = await _run_sync(store.add_photo, f.filename, data)
            created.append(_photo_json(meta))
        except Exception as e:
            log.warning("Upload mislukt (%s): %s", f.filename, e)
            errors.append(f"{f.filename}: geen geldige foto")
    return {"photos": created, "errors": errors}


async def _run_sync(fn, *args):
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(fn, *args)


@app.get("/api/photos/{photo_id}/{kind}")
def photo_file(photo_id: str, kind: str):
    if kind not in ("preview", "thumb"):
        raise HTTPException(404)
    return FileResponse(
        store.file_path(photo_id, kind),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


class StateBody(BaseModel):
    state: dict | None = None


@app.put("/api/photos/{photo_id}/state")
def save_state(photo_id: str, body: StateBody):
    return _photo_json(store.update_meta(photo_id, state=body.state))


@app.delete("/api/photos/{photo_id}")
def delete_photo(photo_id: str):
    store.delete_photo(photo_id)
    return {"ok": True}


class UpscaleBody(BaseModel):
    factor: int = 4


@app.post("/api/photos/{photo_id}/upscale")
def upscale(photo_id: str, body: UpscaleBody):
    if body.factor not in (2, 4):
        raise HTTPException(400, "Kies 2x of 4x")
    store.get_meta(photo_id)
    job = upscaler.job_for_photo(photo_id)
    if job and job["status"] in ("queued", "running"):
        return job
    return upscaler.submit(photo_id, body.factor)


@app.post("/api/photos/{photo_id}/reset-upscale")
def reset_upscale(photo_id: str):
    job = upscaler.job_for_photo(photo_id)
    if job and job["status"] in ("queued", "running"):
        raise HTTPException(409, "Upscalen is nog bezig")
    return _photo_json(store.reset_upscale(photo_id))


@app.post("/api/photos/{photo_id}/auto")
def auto_adjust(photo_id: str):
    img, _ = open_rgb(store.file_path(photo_id, "preview"))
    return auto.suggest(img)


@app.get("/api/presets")
def list_presets():
    return presets.all_presets()


class PresetBody(BaseModel):
    name: str
    params: dict


@app.post("/api/presets")
def create_preset(body: PresetBody):
    return presets.add_custom(body.name, body.params)


@app.delete("/api/presets/{preset_id}")
def remove_preset(preset_id: str):
    if not presets.delete_custom(preset_id):
        raise HTTPException(404, "Preset niet gevonden")
    return {"ok": True}


class ExportBody(BaseModel):
    photo_ids: list[str]
    state: dict | None = None  # None = ieder zijn eigen instellingen


def render_export(photo_id, state, by_id):
    meta = store.get_meta(photo_id)
    st = state if state is not None else meta.get("state")
    params = effective_params(st, by_id)
    img = store.load_working(photo_id)
    arr = apply_edits(np.asarray(img), params)
    return meta, Image.fromarray(arr)


@app.post("/api/export")
def export(body: ExportBody):
    if not body.photo_ids:
        raise HTTPException(400, "Geen foto's gekozen")
    by_id = presets.presets_by_id()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    outputs = []
    used = set()
    for pid in body.photo_ids:
        meta, img = render_export(pid, body.state, by_id)
        name = _safe_name(meta["name"])
        if meta.get("upscaled"):
            name += f"_{meta['upscaled']}x"
        fname = f"{name}_edit.jpg"
        i = 2
        while fname in used or (EXPORT_DIR / fname).exists():
            fname = f"{name}_edit_{i}.jpg"
            i += 1
        used.add(fname)
        save_jpeg(img, EXPORT_DIR / fname, JPEG_QUALITY, store.icc_profile(pid))
        outputs.append(fname)

    if len(outputs) == 1:
        return {"url": f"/api/exports/{outputs[0]}", "filename": outputs[0], "count": 1,
                "folder": str(EXPORT_DIR)}
    for old in EXPORTS_DIR.glob("fotostudio_*.zip"):  # oude zips opruimen
        if time.time() - old.stat().st_mtime > 24 * 3600:
            old.unlink(missing_ok=True)
    zname = f"fotostudio_{stamp}.zip"
    with zipfile.ZipFile(EXPORTS_DIR / zname, "w", zipfile.ZIP_STORED) as z:
        for fname in outputs:
            z.write(EXPORT_DIR / fname, fname)
    return {"url": f"/api/exports/{zname}", "filename": zname, "count": len(outputs),
            "folder": str(EXPORT_DIR)}


@app.get("/api/exports/{name}")
def download(name: str):
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(404)
    for d in (EXPORT_DIR, EXPORTS_DIR):
        f = d / name
        if f.is_file():
            media = "application/zip" if name.endswith(".zip") else "image/jpeg"
            return FileResponse(f, media_type=media, filename=name)
    raise HTTPException(404)


@app.post("/api/open-export-folder")
def open_folder(request: Request):
    if not _is_local(request):
        raise HTTPException(403, "Alleen op de computer zelf")
    path = str(EXPORT_DIR)
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
    return {"ok": True}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

__all__ = ["app", "DATA_DIR"]
