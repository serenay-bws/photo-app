"""Opslag van geüploade foto's in data/photos/<id>/."""

import json
import re
import shutil
import threading
import time
import uuid

from .config import PHOTOS_DIR, PREVIEW_LONG, THUMB_LONG
from .imaging import open_rgb, resized, save_jpeg

_lock = threading.RLock()
_ID_RE = re.compile(r"^[a-f0-9]{12}$")


class PhotoNotFound(KeyError):
    pass


def _dir(photo_id):
    if not _ID_RE.match(photo_id or ""):
        raise PhotoNotFound(photo_id)
    d = PHOTOS_DIR / photo_id
    if not (d / "meta.json").exists():
        raise PhotoNotFound(photo_id)
    return d


def _write_meta(d, meta):
    tmp = d / "meta.tmp"
    tmp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    tmp.replace(d / "meta.json")


def get_meta(photo_id):
    return json.loads((_dir(photo_id) / "meta.json").read_text(encoding="utf-8"))


def update_meta(photo_id, **changes):
    with _lock:
        d = _dir(photo_id)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        meta.update(changes)
        _write_meta(d, meta)
        return meta


def list_photos():
    items = []
    for d in PHOTOS_DIR.iterdir():
        try:
            items.append(get_meta(d.name))
        except (PhotoNotFound, OSError, ValueError):
            continue
    return sorted(items, key=lambda m: m.get("created", 0))


def _make_previews(d, img, icc):
    save_jpeg(resized(img, PREVIEW_LONG), d / "preview.jpg", 90, icc)
    save_jpeg(resized(img, THUMB_LONG), d / "thumb.jpg", 85, icc)


def add_photo(filename, data):
    """Sla een upload op. Gooit een fout als het geen geldige afbeelding is."""
    img, icc = open_rgb(data)
    photo_id = uuid.uuid4().hex[:12]
    d = PHOTOS_DIR / photo_id
    d.mkdir(parents=True)
    try:
        # Origineel (rechtgezet) verliesvrij bewaren; zo werkt ook HEIC overal
        img.save(d / "original.png", compress_level=1, icc_profile=icc)
        _make_previews(d, img, icc)
        if icc:
            (d / "icc.bin").write_bytes(icc)
        meta = {
            "id": photo_id,
            "name": re.sub(r"[^\w\-. ]", "_", filename or "foto")[:80],
            "width": img.width,
            "height": img.height,
            "orig_width": img.width,
            "orig_height": img.height,
            "upscaled": 0,
            "version": 1,
            "state": None,
            "created": time.time(),
        }
        _write_meta(d, meta)
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise
    return meta


def file_path(photo_id, kind):
    d = _dir(photo_id)
    if kind == "preview":
        return d / "preview.jpg"
    if kind == "thumb":
        return d / "thumb.jpg"
    if kind == "original":
        return d / "original.png"
    if kind == "working":
        up = d / "upscaled.png"
        return up if up.exists() else d / "original.png"
    raise ValueError(kind)


def icc_profile(photo_id):
    f = _dir(photo_id) / "icc.bin"
    return f.read_bytes() if f.exists() else None


def load_working(photo_id):
    img, _ = open_rgb(file_path(photo_id, "working"))
    return img


def set_upscaled(photo_id, img, factor):
    with _lock:
        d = _dir(photo_id)
        icc = icc_profile(photo_id)
        tmp = d / "upscaled.tmp.png"
        img.save(tmp, compress_level=1, icc_profile=icc)
        tmp.replace(d / "upscaled.png")
        _make_previews(d, img, icc)
        meta = get_meta(photo_id)
        return update_meta(
            photo_id,
            width=img.width,
            height=img.height,
            upscaled=factor,
            version=meta.get("version", 1) + 1,
        )


def reset_upscale(photo_id):
    with _lock:
        d = _dir(photo_id)
        (d / "upscaled.png").unlink(missing_ok=True)
        img, icc = open_rgb(d / "original.png")
        _make_previews(d, img, icc)
        meta = get_meta(photo_id)
        return update_meta(
            photo_id,
            width=img.width,
            height=img.height,
            upscaled=0,
            version=meta.get("version", 1) + 1,
        )


def delete_photo(photo_id):
    with _lock:
        shutil.rmtree(_dir(photo_id), ignore_errors=True)
