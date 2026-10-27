"""Webserver (FastAPI). Alles draait lokaal op deze computer."""

import io
import logging
import mimetypes
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

from . import auth, auto, match, presets, store
from .config import DATA_DIR, EXPORTS_DIR, JPEG_QUALITY, STATIC_DIR
from .edits import apply_edits, effective_params
from .geometry import apply_geometry
from .imaging import open_rgb, save_jpeg
from .tunnel import load_settings as tunnel_settings
from .tunnel import save_settings as save_tunnel_settings
from .tunnel import tunnel
from .upscaler import target_size, upscaler

log = logging.getLogger("fotostudio")
mimetypes.add_type("application/manifest+json", ".webmanifest")


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

def active_port():
    return int(os.environ.get("FOTOSTUDIO_ACTIVE_PORT", os.environ.get("FOTOSTUDIO_PORT", 8000)))


@asynccontextmanager
async def _lifespan(_app):
    upscaler.start()
    if tunnel_settings()["enabled"] and auth.password_set():
        tunnel.start(active_port())
    yield
    tunnel.stop()


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
    if job and job["status"] == "done":
        # meta kan net vóór het afronden gelezen zijn; nu is hij definitief
        meta = store.get_meta(meta["id"])
    out = dict(meta)
    v = meta.get("version", 1)
    out["preview_url"] = f"/api/photos/{meta['id']}/preview?v={v}"
    out["thumb_url"] = f"/api/photos/{meta['id']}/thumb?v={v}"
    out["targets"] = {
        str(f): target_size(meta["orig_width"], meta["orig_height"], f) for f in (1, 2, 4)
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


LOOPBACK = ("127.0.0.1", "::1", "localhost")
PROXY_HEADERS = ("cf-connecting-ip", "cf-ray", "x-forwarded-for", "x-forwarded-host")


def _is_local(request: Request):
    """Alleen echt op deze computer zelf; verkeer via de Cloudflare-tunnel telt niet."""
    host = request.client.host if request.client else ""
    return host in LOOPBACK and not any(h in request.headers for h in PROXY_HEADERS)


def _client_ip(request: Request):
    host = request.client.host if request.client else "?"
    if host in LOOPBACK and "cf-connecting-ip" in request.headers:
        return request.headers["cf-connecting-ip"]
    return host


def _authorized(request: Request):
    return _is_local(request) or auth.valid_session(request.cookies.get(auth.COOKIE))


PUBLIC_API = {"/api/auth/status", "/api/auth/login"}


@app.middleware("http")
async def _security(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in PUBLIC_API and not _authorized(request):
        return JSONResponse({"detail": "Log eerst in"}, status_code=401)
    response = await call_next(request)
    if path.startswith("/api/"):
        cc = response.headers.get("cache-control", "")
        # nooit laten cachen door Cloudflare of andere tussenpartijen
        response.headers["cache-control"] = "private, " + cc if cc and "private" not in cc else (cc or "no-store")
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["referrer-policy"] = "no-referrer"
    response.headers["x-frame-options"] = "DENY"
    return response


def _require_local(request: Request):
    if not _is_local(request):
        raise HTTPException(403, "Dit kan alleen op de computer zelf")


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
        "tunnel": tunnel.info(),
        "password_set": auth.password_set(),
    }


# ------------------------------------------------------------------ inloggen


@app.get("/api/auth/status")
def auth_status(request: Request):
    return {
        "authenticated": _authorized(request),
        "is_local": _is_local(request),
        "password_set": auth.password_set(),
    }


class LoginBody(BaseModel):
    password: str


@app.post("/api/auth/login")
def do_login(body: LoginBody, request: Request):
    try:
        token = auth.login(body.password, _client_ip(request))
    except PermissionError as e:
        raise HTTPException(401, str(e))
    secure = request.headers.get("x-forwarded-proto") == "https" or request.url.scheme == "https"
    resp = JSONResponse({"ok": True})
    resp.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True,
                    secure=secure, samesite="lax", path="/")
    return resp


@app.post("/api/auth/logout")
def do_logout(request: Request):
    auth.logout(request.cookies.get(auth.COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


class PasswordBody(BaseModel):
    password: str


@app.post("/api/auth/password")
def change_password(body: PasswordBody, request: Request):
    _require_local(request)
    try:
        auth.set_password(body.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


# ------------------------------------------------------------------ cloudflare


class TunnelBody(BaseModel):
    enabled: bool
    token: str | None = None
    hostname: str | None = None


@app.post("/api/tunnel")
def set_tunnel(body: TunnelBody, request: Request):
    _require_local(request)
    if body.enabled and not auth.password_set():
        raise HTTPException(400, "Stel eerst een wachtwoord in")
    changes = {"enabled": body.enabled}
    if body.token is not None:
        changes["token"] = body.token.strip()
    if body.hostname is not None:
        changes["hostname"] = re.sub(r"^https?://", "", body.hostname.strip()).strip("/")
    old = tunnel_settings()
    new = save_tunnel_settings(**changes)
    if not body.enabled or new["token"] != old["token"]:
        tunnel.stop()
    if body.enabled:
        tunnel.start(active_port())
    return tunnel.info()


@app.get("/api/qr")
def qr(request: Request, target: str = "lan"):
    import qrcode
    import qrcode.image.svg

    ip = lan_ip()
    url = f"http://{ip}:{request.url.port or 80}" if ip else str(request.base_url)
    if target == "public" and tunnel.url:
        url = tunnel.url
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
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
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
    if body.factor not in (1, 2, 4):
        raise HTTPException(400, "Kies 1x (verbeteren), 2x of 4x")
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


@app.post("/api/photos/{photo_id}/match")
async def match_look(photo_id: str, reference: UploadFile = File(...)):
    """Kopieer de look van een voorbeeldfoto en bewaar die als eigen preset."""
    data = await reference.read()
    try:
        ref, _ = open_rgb(data)
    except Exception:
        raise HTTPException(400, "Dat voorbeeld is geen geldige foto")
    img, _ = open_rgb(store.file_path(photo_id, "preview"))
    params, _before, _after = await _run_sync(match.match_look, img, ref)
    looks = [p for p in presets.all_presets() if p["name"].startswith("Look ")]
    preset = presets.add_custom(f"Look {len(looks) + 1}", params)
    return {"preset": preset, "summary": match.describe(params)}


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
    own = meta.get("state") or {}
    st = state if state is not None else own
    params = effective_params(st, by_id)
    # bijsnijden hoort altijd bij de foto zelf, ook bij "alle foto's met deze instellingen"
    img = apply_geometry(store.load_working(photo_id), own.get("crop"))
    arr = apply_edits(np.asarray(img.convert("RGB")), params)
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
        if meta.get("upscaled") == 1:
            name += "_ai"
        elif meta.get("upscaled"):
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
    _require_local(request)
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
