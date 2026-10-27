"""Tunnelbeheer, getest met een nagebootst cloudflared-programma."""

import sys
import time

import pytest

from app import tunnel as tunnel_mod

pytestmark = pytest.mark.skipif(sys.platform.startswith("win"), reason="nep-programma is een shellscript")

FAKE = """#!/bin/sh
echo "INF Requesting new quick Tunnel on trycloudflare.com..."
echo "INF |  https://blauwe-zee-test-42.trycloudflare.com  |"
echo "args: $*"
sleep 30
"""


def wait_for(cond, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_quick_tunnel_reports_url_and_stops(monkeypatch):
    exe = tunnel_mod._exe_path()
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text(FAKE)
    exe.chmod(0o755)
    t = tunnel_mod.Tunnel()
    try:
        t.start(8123)
        assert wait_for(lambda: t.state == "on")
        assert t.url == "https://blauwe-zee-test-42.trycloudflare.com"
    finally:
        t.stop()
    assert t.state == "off" and t.url is None
    exe.unlink()


def test_settings_roundtrip():
    tunnel_mod.save_settings(enabled=True, token="abc", hostname="foto.example.com")
    s = tunnel_mod.load_settings()
    assert s == {"enabled": True, "token": "abc", "hostname": "foto.example.com"}
    tunnel_mod.save_settings(enabled=False, token="", hostname="")
