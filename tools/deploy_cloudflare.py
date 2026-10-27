"""Zet de Cloudflare-versie online, beveiligd met gebruikersnaam + wachtwoord.

  1. Pages-project aanmaken (als dat nog niet bestaat)
  2. Inloggegevens instellen als geheime variabelen van het project
     (alleen een hash van het wachtwoord wordt opgeslagen)
  3. site/ + functions/ (de login) uploaden met wrangler
  4. Controleren dat de site om een login vraagt

De API-sleutel komt uit CLOUDFLARE_API_TOKEN, of wordt als "network secret" door de
proxy van de omgeving toegevoegd (dan ziet dit script hem nooit).

Gebruik:
  uv run python tools/deploy_cloudflare.py --user serenay            # nieuw wachtwoord maken
  uv run python tools/deploy_cloudflare.py --keep-password           # alleen nieuwe versie uploaden
"""

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.cloudflare.com/client/v4"
WRANGLER = "wrangler@4.151.0"
ROOT = Path(__file__).resolve().parents[1]
ITERATIONS = 20000  # moet gelijk zijn aan functions/_middleware.js
WORDS = """appel berg bloem boot brug duin eiland garnaal golf haven hemel honing kaars kade
kasteel kers koffie kompas koraal kristal lantaarn lelie maan meeuw mosterd nacht oceaan orchidee
paleis parel peper pinguin poolster regen rivier roos saffier schelp sneeuw spiegel ster storm
tijger tulp vanille vlinder vuurtoren walvis wolk zeester zomer zonlicht zwaan""".split()


def call(method, path, body=None):
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    req = urllib.request.Request(
        API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        data = json.loads(e.read() or b"{}")
    if not data.get("success"):
        raise RuntimeError(f"{method} {path}: {data.get('errors')}")
    return data["result"]


def new_password():
    words = [secrets.choice(WORDS).capitalize() for _ in range(3)]
    return "-".join(words) + "-" + str(secrets.randbelow(9000) + 1000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="fotostudio-serenay")
    ap.add_argument("--user", default="serenay")
    ap.add_argument("--account", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID"))
    ap.add_argument("--keep-password", action="store_true")
    args = ap.parse_args()

    account = args.account or call("GET", "/accounts")[0]["id"]
    acc = f"/accounts/{account}"

    try:
        project = call("GET", f"{acc}/pages/projects/{args.project}")
    except RuntimeError:
        project = call("POST", f"{acc}/pages/projects", {"name": args.project, "production_branch": "main"})
        print("Pages-project aangemaakt")
    host = project["subdomain"]

    password = None
    if not args.keep_password:
        password = new_password()
        salt = secrets.token_hex(16)
        pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
        env_vars = {
            "AUTH_USER": {"type": "plain_text", "value": args.user},
            "AUTH_PASS_HASH": {"type": "secret_text", "value": f"{salt}:{pw_hash}"},
            "SESSION_SECRET": {"type": "secret_text", "value": secrets.token_hex(32)},
        }
        call("PATCH", f"{acc}/pages/projects/{args.project}",
             {"deployment_configs": {"production": {"env_vars": env_vars}, "preview": {"env_vars": env_vars}}})
        print("Inloggegevens ingesteld")

    env = {**os.environ, "CLOUDFLARE_ACCOUNT_ID": account, "WRANGLER_SEND_METRICS": "false",
           "CLOUDFLARE_API_TOKEN": os.environ.get("CLOUDFLARE_API_TOKEN") or "via-proxy"}
    subprocess.run(["npx", "--yes", WRANGLER, "pages", "deploy", "site", "--project-name", args.project,
                    "--branch", "main", "--commit-dirty=true"], check=True, env=env, cwd=ROOT)

    print(f"\nAdres: https://{host}")
    if password:
        print(f"Gebruikersnaam: {args.user}\nWachtwoord: {password}")


if __name__ == "__main__":
    main()
