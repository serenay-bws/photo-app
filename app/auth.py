"""Inloggen met een wachtwoord.

Op de computer zelf (localhost) heb je geen wachtwoord nodig. Iedereen die de app
via het netwerk of via Cloudflare opent, moet inloggen.
"""

import hashlib
import hmac
import json
import secrets
import threading
import time

from .config import DATA_DIR

AUTH_FILE = DATA_DIR / "auth.json"
COOKIE = "fs_session"
SESSION_DAYS = 30
MIN_PASSWORD = 8
_ITERATIONS = 600_000

# beveiliging tegen raden: per IP en voor alle IP's samen
MAX_FAILS_PER_IP = 5
MAX_FAILS_TOTAL = 30
LOCK_SECONDS = 15 * 60

_lock = threading.Lock()
_fails = {}  # ip -> [tijdstippen]
_all_fails = []


def _load():
    try:
        return json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data):
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = AUTH_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(AUTH_FILE)


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS).hex()


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def password_set():
    return "password" in _load()


def set_password(password):
    """Nieuw wachtwoord; alle bestaande sessies worden ongeldig."""
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"Kies een wachtwoord van minstens {MIN_PASSWORD} tekens")
    salt = secrets.token_hex(16)
    with _lock:
        _save({"password": {"salt": salt, "hash": _hash(password, salt)}, "sessions": {}})


def _locked(ip, now):
    recent = [t for t in _fails.get(ip, []) if now - t < LOCK_SECONDS]
    _fails[ip] = recent
    _all_fails[:] = [t for t in _all_fails if now - t < LOCK_SECONDS]
    return len(recent) >= MAX_FAILS_PER_IP or len(_all_fails) >= MAX_FAILS_TOTAL


def login(password, ip):
    """Geeft een sessie-token, of gooit PermissionError met een uitleg."""
    now = time.time()
    with _lock:
        if _locked(ip, now):
            raise PermissionError("Te vaak een fout wachtwoord. Probeer het over 15 minuten opnieuw.")
        data = _load()
        pw = data.get("password")
        if not pw:
            raise PermissionError("Er is nog geen wachtwoord ingesteld. Doe dat eerst op je computer.")
        ok = hmac.compare_digest(_hash(password or "", pw["salt"]), pw["hash"])
        if not ok:
            _fails.setdefault(ip, []).append(now)
            _all_fails.append(now)
            raise PermissionError("Wachtwoord klopt niet")
        _fails.pop(ip, None)
        token = secrets.token_urlsafe(32)
        sessions = {k: v for k, v in data.get("sessions", {}).items() if v > now}
        sessions[_token_hash(token)] = now + SESSION_DAYS * 86400
        data["sessions"] = sessions
        _save(data)
        return token


def valid_session(token):
    if not token:
        return False
    expires = _load().get("sessions", {}).get(_token_hash(token))
    return bool(expires and expires > time.time())


def logout(token):
    if not token:
        return
    with _lock:
        data = _load()
        data.get("sessions", {}).pop(_token_hash(token), None)
        _save(data)
