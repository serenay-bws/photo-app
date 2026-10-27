"""Inloggen van de Cloudflare-versie (functions/_middleware.js), getest met node."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
node = shutil.which("node")


def pass_hash(password, salt="00112233445566778899aabbccddeeff"):
    return salt + ":" + hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 20000).hex()


SCRIPT = """
import { onRequest } from "./functions/_middleware.js";
const env = %s;
const next = async () => new Response("APP", { status: 200 });
const call = (path, init = {}) => onRequest({ request: new Request("https://x.pages.dev" + path, init), env, next });
const out = {};
let r = await call("/", { headers: { accept: "text/html" } });
out.anon = [r.status, (await r.text()).includes("Inloggen")];
r = await call("/js/app.js");
out.anonAsset = r.status;
r = await call("/icon-180.png");
out.icon = r.status;
const form = (u, p) => { const f = new FormData(); f.set("username", u); f.set("password", p); return f; };
r = await call("/login", { method: "POST", body: form("serenay", "fout") });
out.wrong = r.status;
r = await call("/login", { method: "POST", body: form("Serenay ", "Geheim-Woord-42") });
out.ok = r.status;
const cookie = r.headers.get("set-cookie");
out.cookieFlags = ["HttpOnly", "Secure", "SameSite=Lax", "Max-Age=31536000"].every((f) => cookie.includes(f));
const value = cookie.split(";")[0];
r = await call("/", { headers: { cookie: value, accept: "text/html" } });
out.loggedIn = await r.text();
const [exp, sig] = value.split("=")[1].split(".");
r = await call("/", { headers: { cookie: `fs_session=${Number(exp) + 1}.${sig}` } });
out.tampered = r.status;
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(not node, reason="node niet geïnstalleerd")
def test_cloudflare_login_flow():
    env = {"AUTH_USER": "serenay", "AUTH_PASS_HASH": pass_hash("Geheim-Woord-42"), "SESSION_SECRET": "s3cr3t"}
    r = subprocess.run([node, "--input-type=module"], input=SCRIPT % json.dumps(env), cwd=ROOT,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["anon"] == [200, True]       # loginscherm
    assert out["anonAsset"] == 401          # app-bestanden afgeschermd
    assert out["icon"] == 200               # icoon mag (beginscherm)
    assert out["wrong"] == 401
    assert out["ok"] == 303 and out["cookieFlags"]
    assert out["loggedIn"] == "APP"
    assert out["tampered"] == 401           # vervalste sessie werkt niet
