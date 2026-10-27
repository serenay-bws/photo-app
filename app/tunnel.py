"""Cloudflare Tunnel: maakt de app (met wachtwoord) overal bereikbaar.

Twee manieren:
  * Snel (standaard): een gratis "quick tunnel" zonder account. Je krijgt een
    willekeurig adres zoals https://xxx.trycloudflare.com dat bij elke start verandert.
  * Vast adres: met je eigen Cloudflare-account maak je een tunnel aan en plak je de
    tunnel-token in de app. Dan blijft het adres altijd hetzelfde.

Het programma `cloudflared` wordt eenmalig van GitHub gedownload (checksum gecontroleerd).
Je foto's blijven op je computer; Cloudflare stuurt alleen het verkeer door.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import urllib.request

from .config import BIN_DIR, DATA_DIR

log = logging.getLogger("fotostudio.tunnel")

VERSION = "2026.10.0"
RELEASE = f"https://github.com/cloudflare/cloudflared/releases/download/{VERSION}/"
ASSETS = {
    ("windows", "amd64"): ("cloudflared-windows-amd64.exe",
                           "86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c"),
    ("macos", "arm64"): ("cloudflared-darwin-arm64.tgz",
                         "a2f79ff7b9420aa537d74af239f376da170bbabeb529aec416002adac6a72e70"),
    ("macos", "amd64"): ("cloudflared-darwin-amd64.tgz",
                         "903845b81828c8cb3c5d13d816a2de71c06a3da5785469df8eb0e1b736d92f9f"),
    ("linux", "amd64"): ("cloudflared-linux-amd64",
                         "d33ff2d14475178d2012c2c56beba87389ac5ded27649519f198a7d3134a99db"),
    ("linux", "arm64"): ("cloudflared-linux-arm64",
                         "e6422b9d4f72d3194bc5a38676f13667c06666523217b842a877d72a80b5ac08"),
}
SETTINGS_FILE = DATA_DIR / "tunnel.json"
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def _platform():
    import platform

    os_name = "windows" if sys.platform.startswith("win") else "macos" if sys.platform == "darwin" else "linux"
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
    return os_name, arch


def _exe_path():
    os_name, _ = _platform()
    return BIN_DIR / ("cloudflared.exe" if os_name == "windows" else "cloudflared")


def ensure_binary():
    exe = _exe_path()
    if exe.exists():
        return exe
    key = _platform()
    if key not in ASSETS:
        raise RuntimeError("Cloudflare Tunnel wordt op deze computer niet ondersteund")
    name, sha = ASSETS[key]
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = BIN_DIR / (name + ".part")
    log.info("Cloudflare Tunnel downloaden (eenmalig)...")
    with urllib.request.urlopen(RELEASE + name, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    if hashlib.sha256(tmp.read_bytes()).hexdigest() != sha:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("download van Cloudflare Tunnel is beschadigd")
    if name.endswith(".tgz"):
        with tarfile.open(tmp) as t:
            member = t.getmember("cloudflared")
            with t.extractfile(member) as src, open(exe, "wb") as dst:
                shutil.copyfileobj(src, dst)
        tmp.unlink()
    else:
        tmp.replace(exe)
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if key[0] == "macos":
        subprocess.run(["xattr", "-d", "com.apple.quarantine", str(exe)], capture_output=True, check=False)
    return exe


def load_settings():
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"enabled": bool(data.get("enabled")), "token": data.get("token") or "",
            "hostname": data.get("hostname") or ""}


def save_settings(**changes):
    data = load_settings()
    data.update(changes)
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(SETTINGS_FILE)
    return data


class Tunnel:
    def __init__(self):
        self.state = "off"  # off | starting | on | error
        self.url = None
        self.message = ""
        self.port = None
        self._proc = None
        self._lock = threading.Lock()

    def info(self):
        s = load_settings()
        return {"state": self.state, "url": self.url, "message": self.message,
                "enabled": s["enabled"], "mode": "token" if s["token"] else "quick",
                "hostname": s["hostname"]}

    def start(self, port):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return
            self.port = port
            self.state, self.url, self.message = "starting", None, "Verbinden met Cloudflare..."
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        with self._lock:
            proc, self._proc = self._proc, None
            self.state, self.url, self.message = "off", None, ""
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _run(self):
        try:
            exe = ensure_binary()
        except Exception as e:
            log.warning("Cloudflare Tunnel: %s", e)
            self.state, self.message = "error", f"Kon Cloudflare Tunnel niet downloaden: {e}"
            return
        s = load_settings()
        env = dict(os.environ)
        if s["token"]:
            env["TUNNEL_TOKEN"] = s["token"]  # niet op de opdrachtregel (zichtbaar voor andere programma's)
            cmd = [str(exe), "tunnel", "--no-autoupdate", "run"]
        else:
            cmd = [str(exe), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{self.port}"]
        flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                errors="replace", creationflags=flags, env=env)
        with self._lock:
            if self.state == "off":  # intussen uitgezet
                proc.terminate()
                return
            self._proc = proc
        last = ""
        for line in proc.stdout:
            line = line.strip()
            if line:
                last = line
            m = URL_RE.search(line)
            if m and not s["token"]:
                self.url, self.state, self.message = m.group(0), "on", "Actief"
                log.info("Overal bereikbaar via %s", self.url)
            elif s["token"] and "Registered tunnel connection" in line:
                self.state, self.message = "on", "Actief"
                self.url = f"https://{s['hostname']}" if s["hostname"] else None
        code = proc.wait()
        with self._lock:
            if self._proc is proc:  # niet zelf gestopt
                self._proc = None
                self.state, self.url = "error", None
                self.message = f"Verbinding met Cloudflare verbroken ({code}): {last[-160:]}"


tunnel = Tunnel()
