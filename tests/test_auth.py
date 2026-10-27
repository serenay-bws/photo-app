"""Beveiliging: wachtwoord, sessies, tunnel-verkeer en caching."""

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app

PW = "geheim-wachtwoord"


@pytest.fixture()
def fresh_auth():
    auth.AUTH_FILE.unlink(missing_ok=True)
    auth._fails.clear()
    auth._all_fails.clear()
    yield
    auth._fails.clear()
    auth._all_fails.clear()


def remote():
    return TestClient(app, client=("192.168.1.50", 5000))


def local():
    return TestClient(app, client=("127.0.0.1", 5000))


def test_remote_needs_login(fresh_auth):
    auth.set_password(PW)
    c = remote()
    assert c.get("/api/photos").status_code == 401
    assert c.get("/api/auth/status").json() == {"authenticated": False, "is_local": False, "password_set": True}
    assert c.post("/api/auth/login", json={"password": "fout-fout"}).status_code == 401
    r = c.post("/api/auth/login", json={"password": PW})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert c.get("/api/photos").status_code == 200
    c.post("/api/auth/logout")
    assert c.get("/api/photos").status_code == 401


def test_local_computer_needs_no_password(fresh_auth):
    assert local().get("/api/photos").status_code == 200


def test_tunnel_traffic_is_never_local(fresh_auth):
    """cloudflared verbindt via 127.0.0.1, maar dat verkeer komt van internet."""
    c = local()
    h = {"cf-connecting-ip": "203.0.113.9", "cf-ray": "abc"}
    assert c.get("/api/photos", headers=h).status_code == 401
    assert c.post("/api/auth/password", json={"password": "nieuw-wachtwoord"}, headers=h).status_code == 401


def test_without_password_remote_cannot_login(fresh_auth):
    r = remote().post("/api/auth/login", json={"password": "wat-dan-ook"})
    assert r.status_code == 401 and "computer" in r.json()["detail"]


def test_lockout_after_wrong_passwords(fresh_auth):
    auth.set_password(PW)
    c = remote()
    for _ in range(auth.MAX_FAILS_PER_IP):
        c.post("/api/auth/login", json={"password": "verkeerd!!"})
    r = c.post("/api/auth/login", json={"password": PW})  # zelfs goed wachtwoord even geblokkeerd
    assert r.status_code == 401 and "15 minuten" in r.json()["detail"]
    other = TestClient(app, client=("192.168.1.51", 5000))
    assert other.post("/api/auth/login", json={"password": PW}).status_code == 200


def test_password_rules_and_only_local_can_change(fresh_auth):
    assert local().post("/api/auth/password", json={"password": "kort"}).status_code == 400
    assert local().post("/api/auth/password", json={"password": PW}).status_code == 200
    c = remote()
    c.post("/api/auth/login", json={"password": PW})
    assert c.post("/api/auth/password", json={"password": "overgenomen!"}).status_code == 403
    assert c.post("/api/tunnel", json={"enabled": True}).status_code == 403


def test_new_password_logs_everyone_out(fresh_auth):
    auth.set_password(PW)
    c = remote()
    c.post("/api/auth/login", json={"password": PW})
    auth.set_password("ander-wachtwoord")
    assert c.get("/api/photos").status_code == 401


def test_api_responses_are_never_publicly_cached(fresh_auth):
    r = local().get("/api/presets")
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-frame-options"] == "DENY"


def test_tunnel_requires_password_first(fresh_auth):
    r = local().post("/api/tunnel", json={"enabled": True})
    assert r.status_code == 400
