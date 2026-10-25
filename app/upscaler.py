"""AI-upscaling met Real-ESRGAN.

Twee motoren, de app kiest automatisch:
  * GPU: de officiële realesrgan-ncnn-vulkan (model realesrgan-x4plus).
    Werkt met vrijwel elke videokaart (NVIDIA, AMD, Intel, Apple) via Vulkan.
    Wordt bij de eerste start eenmalig gedownload van GitHub.
  * CPU: Real-ESRGAN "realesr-general-x4v3" via ONNX Runtime. Werkt altijd,
    ook zonder videokaart (trager, maar prima).
"""

import hashlib
import logging
import os
import queue
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from . import store
from .imaging import open_rgb
from .config import BIN_DIR, MAX_UPSCALE_LONG, MODELS_DIR

log = logging.getLogger("fotostudio.upscaler")

NCNN_RELEASE = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/"
NCNN_ZIPS = {
    "windows": ("realesrgan-ncnn-vulkan-20220424-windows.zip",
                "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d"),
    "macos": ("realesrgan-ncnn-vulkan-20220424-macos.zip",
              "e0ad05580abfeb25f8d8fb55aaf7bedf552c375b5b4d9bd3c8d59764d2cc333a"),
    "linux": ("realesrgan-ncnn-vulkan-20220424-ubuntu.zip",
              "e5aa6eb131234b87c0c51f82b89390f5e3e642b7b70f2b9bbe95b6a285a40c96"),
}
NCNN_DIR = BIN_DIR / "realesrgan-ncnn-vulkan"
ONNX_MODEL = MODELS_DIR / "realesr-general-x4v3.onnx"
SOFTWARE_GPUS = ("llvmpipe", "lavapipe", "swiftshader", "softpipe", "basic render")
MODEL_SCALE = 4
# Het AI-model krijgt nooit een invoer groter dan dit (lange zijde)
MAX_MODEL_INPUT = max(512, MAX_UPSCALE_LONG // 2)


def _platform():
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _ncnn_exe():
    return NCNN_DIR / ("realesrgan-ncnn-vulkan.exe" if _platform() == "windows" else "realesrgan-ncnn-vulkan")


def target_size(width, height, factor):
    """Doelgrootte na upscalen, begrensd op MAX_UPSCALE_LONG."""
    long = max(width, height)
    scale = min(float(factor), MAX_UPSCALE_LONG / long)
    scale = max(scale, 1.0)
    return max(1, round(width * scale)), max(1, round(height * scale))


# --------------------------------------------------------------------- motoren


class OnnxEngine:
    name = "cpu"

    def __init__(self):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(ONNX_MODEL), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self.label = "Processor · Real-ESRGAN general-x4v3"
        self.device = "processor"

    def upscale(self, img, progress, tile=256, pad=12):
        a = np.asarray(img, dtype=np.float32) / 255.0
        h, w = a.shape[:2]
        s = MODEL_SCALE
        out = np.empty((h * s, w * s, 3), dtype=np.uint8)
        tiles = [(y, x) for y in range(0, h, tile) for x in range(0, w, tile)]
        for i, (y, x) in enumerate(tiles):
            y0, x0 = max(0, y - pad), max(0, x - pad)
            y1, x1 = min(h, y + tile + pad), min(w, x + tile + pad)
            inp = a[y0:y1, x0:x1].transpose(2, 0, 1)[None]
            res = self.session.run(None, {"input": np.ascontiguousarray(inp)})[0][0]
            res = res.transpose(1, 2, 0)
            ty1, tx1 = min(h, y + tile), min(w, x + tile)
            crop = res[(y - y0) * s : (ty1 - y0) * s, (x - x0) * s : (tx1 - x0) * s]
            out[y * s : ty1 * s, x * s : tx1 * s] = (np.clip(crop, 0, 1) * 255 + 0.5).astype(np.uint8)
            progress((i + 1) / len(tiles))
        return Image.fromarray(out)


class NcnnEngine:
    name = "gpu"

    def __init__(self, device):
        self.device = device
        self.label = f"Videokaart ({device}) · Real-ESRGAN x4plus"

    @staticmethod
    def run(src, dst, progress=None, timeout=None):
        exe = _ncnn_exe()
        cmd = [str(exe), "-i", str(src), "-o", str(dst), "-n", "realesrgan-x4plus",
               "-s", "4", "-f", "png", "-m", str(NCNN_DIR / "models")]
        flags = subprocess.CREATE_NO_WINDOW if _platform() == "windows" else 0
        proc = subprocess.Popen(
            cmd, cwd=NCNN_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", creationflags=flags,
        )
        lines = []
        timer = threading.Timer(timeout, proc.kill) if timeout else None
        if timer:
            timer.start()
        try:
            for line in proc.stdout:
                line = line.strip()
                lines.append(line)
                m = re.match(r"^(\d+(?:\.\d+)?)%$", line)
                if m and progress:
                    progress(float(m.group(1)) / 100.0)
            code = proc.wait()
        finally:
            if timer:
                timer.cancel()
        return code, lines

    def upscale(self, img, progress):
        with tempfile.TemporaryDirectory(prefix="fotostudio-") as tmp:
            src, dst = Path(tmp) / "in.png", Path(tmp) / "out.png"
            img.save(src, compress_level=1)
            code, lines = self.run(src, dst, progress)
            if code != 0 or not dst.exists():
                raise RuntimeError("GPU-upscaler mislukt: " + " | ".join(lines[-5:]))
            out = Image.open(dst)
            out.load()
            return out.convert("RGB")


def _download_ncnn():
    plat = _platform()
    fname, sha = NCNN_ZIPS[plat]
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    zpath = BIN_DIR / fname
    if not zpath.exists():
        log.info("Real-ESRGAN (GPU) downloaden van GitHub, eenmalig ±50 MB...")
        tmp = zpath.with_suffix(".part")
        with urllib.request.urlopen(NCNN_RELEASE + fname, timeout=60) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        tmp.replace(zpath)
    digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
    if digest != sha:
        zpath.unlink(missing_ok=True)
        raise RuntimeError("download beschadigd (checksum klopt niet)")
    tmpdir = BIN_DIR / "ncnn-extract"
    shutil.rmtree(tmpdir, ignore_errors=True)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmpdir)
    shutil.rmtree(NCNN_DIR, ignore_errors=True)
    tmpdir.replace(NCNN_DIR)
    exe = _ncnn_exe()
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if plat == "macos":
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(NCNN_DIR)],
                       capture_output=True, check=False)
    zpath.unlink(missing_ok=True)


def _probe_ncnn():
    """Test of de GPU-upscaler werkt. Geeft apparaatnaam of None."""
    if not _ncnn_exe().exists():
        _download_ncnn()
    with tempfile.TemporaryDirectory(prefix="fotostudio-probe-") as tmp:
        src, dst = Path(tmp) / "probe.png", Path(tmp) / "probe_out.png"
        rng = np.random.default_rng(1)
        Image.fromarray(rng.integers(0, 255, (32, 32, 3), dtype=np.uint8)).save(src)
        code, lines = NcnnEngine.run(src, dst, timeout=180)
        devices = []
        for line in lines:
            m = re.match(r"^\[(\d+) (.+?)\]\s+queueC=", line)
            if m:
                devices.append(m.group(2))
        if code != 0 or not dst.exists() or not devices:
            log.info("GPU-upscaler niet bruikbaar: %s", " | ".join(lines[-3:]))
            return None
        allow_soft = os.environ.get("FOTOSTUDIO_ALLOW_SOFTWARE_GPU") == "1"
        hw = [d for d in devices if not any(s in d.lower() for s in SOFTWARE_GPUS)]
        if not hw and not allow_soft:
            log.info("Alleen software-Vulkan gevonden (%s); CPU-motor is sneller.", devices)
            return None
        return (hw or devices)[0]


# ------------------------------------------------------------------- wachtrij


class Upscaler:
    def __init__(self):
        self.cpu = None
        self.gpu = None
        self.state = "starting"  # starting | ready
        self.message = "AI-upscaler wordt voorbereid..."
        self.jobs = {}
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._started = False

    def start(self):
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._init_engines, daemon=True).start()
        threading.Thread(target=self._worker, daemon=True).start()

    def _init_engines(self):
        try:
            self.cpu = OnnxEngine()
        except Exception as e:  # pragma: no cover
            log.exception("CPU-motor kon niet laden")
            self.message = f"CPU-motor kon niet laden: {e}"
        mode = os.environ.get("FOTOSTUDIO_ENGINE", "auto").lower()
        if mode != "cpu":
            self.message = "Zoeken naar een geschikte videokaart..."
            try:
                device = _probe_ncnn()
                if device:
                    self.gpu = NcnnEngine(device)
            except Exception as e:
                log.info("GPU-upscaler niet beschikbaar: %s", e)
        self.state = "ready"
        eng = self.engine
        self.message = eng.label if eng else "Geen upscaler beschikbaar"
        log.info("Upscaler: %s", self.message)

    @property
    def engine(self):
        return self.gpu or self.cpu

    def info(self):
        eng = self.engine
        return {
            "state": self.state,
            "message": self.message,
            "engine": eng.name if eng else None,
            "max_side": MAX_UPSCALE_LONG,
        }

    def submit(self, photo_id, factor):
        job = {
            "id": uuid.uuid4().hex[:10],
            "photo_id": photo_id,
            "factor": factor,
            "status": "queued",
            "progress": 0.0,
            "message": "In de wachtrij",
            "eta": None,
            "created": time.time(),
        }
        with self._lock:
            # oude, afgeronde jobs opruimen
            for jid in [j for j, v in self.jobs.items() if v["status"] in ("done", "error")
                        and time.time() - v["created"] > 3600]:
                del self.jobs[jid]
            self.jobs[job["id"]] = job
        self._queue.put(job["id"])
        return job

    def job_for_photo(self, photo_id):
        active = [j for j in self.jobs.values() if j["photo_id"] == photo_id]
        return max(active, key=lambda j: j["created"]) if active else None

    def _worker(self):
        while True:
            job = self.jobs.get(self._queue.get())
            if not job:
                continue
            while self.state != "ready":
                job["message"] = self.message
                time.sleep(0.5)
            self._run(job)

    def _run(self, job):
        job["status"] = "running"
        job["message"] = "Bezig met upscalen..."
        started = time.time()

        def progress(frac, scale=0.92):
            frac = min(max(frac, 0.0), 1.0)
            job["progress"] = frac * scale
            elapsed = time.time() - started
            if frac > 0.03:
                job["eta"] = round(elapsed / frac * (1 - frac))

        try:
            img, _ = open_rgb(store.file_path(job["photo_id"], "original"))
            tw, th = target_size(img.width, img.height, job["factor"])
            if max(img.size) > MAX_MODEL_INPUT:
                s = MAX_MODEL_INPUT / max(img.size)
                img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
            out = None
            if self.gpu:
                try:
                    out = self.gpu.upscale(img, progress)
                except Exception as e:
                    log.warning("GPU mislukt, val terug op CPU: %s", e)
                    job["message"] = "GPU lukte niet, nu via de processor..."
                    started = time.time()
            if out is None:
                if not self.cpu:
                    raise RuntimeError("geen upscaler beschikbaar")
                out = self.cpu.upscale(img, progress)
            job["message"] = "Opslaan..."
            if out.size != (tw, th):
                out = out.resize((tw, th), Image.LANCZOS)
            store.set_upscaled(job["photo_id"], out, job["factor"])
            job.update(status="done", progress=1.0, message="Klaar", eta=0,
                       seconds=round(time.time() - started, 1))
        except store.PhotoNotFound:
            job.update(status="error", message="Foto is verwijderd")
        except Exception as e:
            log.exception("Upscalen mislukt")
            job.update(status="error", message=f"Upscalen mislukt: {e}")


upscaler = Upscaler()
