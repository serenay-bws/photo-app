"""Zet de Cloudflare-versie online en beveilig hem, in één keer.

Volgorde (zo is de app nooit onbeveiligd bereikbaar):
  1. Pages-project aanmaken (nog zonder inhoud)
  2. Cloudflare Access: alleen het opgegeven e-mailadres mag erin (code per mail)
  3. De map site/ uploaden (wrangler pages deploy)
  4. Controleren dat het adres om een login vraagt

Nodig: een Cloudflare API-token met de rechten (óf als omgevingsvariabele
CLOUDFLARE_API_TOKEN, óf als "network secret" voor api.cloudflare.com; dan voegt de
proxy van de omgeving de sleutel zelf toe en ziet dit script hem nooit)
  Account → Cloudflare Pages: Edit
  Account → Access: Apps and Policies: Edit
  Account → Access: Organizations, Identity Providers, and Groups: Edit
  Account → Account Settings: Read

Gebruik:
  uv run python tools/deploy_cloudflare.py --project fotostudio-serenay --email serenayk1@hotmail.com
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

API = "https://api.cloudflare.com/client/v4"
WRANGLER = "wrangler@4.151.0"


def call(method, path, body=None, token=None):
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="fotostudio-serenay")
    ap.add_argument("--email", required=True)
    ap.add_argument("--account", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID"))
    args = ap.parse_args()
    token = os.environ.get("CLOUDFLARE_API_TOKEN")  # leeg = proxy voegt hem toe
    api = lambda m, p, b=None: call(m, p, b, token)  # noqa: E731

    account = args.account
    if not account:
        accounts = api("GET", "/accounts")
        if len(accounts) != 1:
            sys.exit("Meerdere accounts; geef --account op: " + ", ".join(f"{a['name']}={a['id']}" for a in accounts))
        account = accounts[0]["id"]
    acc = f"/accounts/{account}"

    # 1. Pages-project
    try:
        project = api("GET", f"{acc}/pages/projects/{args.project}")
        print("Pages-project bestaat al")
    except RuntimeError:
        project = api("POST", f"{acc}/pages/projects", {"name": args.project, "production_branch": "main"})
        print("Pages-project aangemaakt")
    host = project["subdomain"]  # bv. fotostudio-serenay.pages.dev
    print("Adres:", f"https://{host}")

    # 2. Cloudflare Access
    try:
        api("GET", f"{acc}/access/organizations")
    except RuntimeError:
        sys.exit("Zero Trust is nog niet geactiveerd: open in Cloudflare één keer 'Zero Trust', "
                 "kies een teamnaam en het Free-plan, en draai dit script opnieuw.")
    idps = api("GET", f"{acc}/access/identity_providers")
    if not any(i["type"] == "onetimepin" for i in idps):
        api("POST", f"{acc}/access/identity_providers", {"name": "E-mailcode", "type": "onetimepin", "config": {}})
        print("Inloggen met e-mailcode aangezet")
    apps = api("GET", f"{acc}/access/apps")
    app = next((a for a in apps if a.get("domain") == host), None)
    if not app:
        app = api("POST", f"{acc}/access/apps", {
            "name": "Fotostudio", "type": "self_hosted", "domain": host,
            "self_hosted_domains": [host, f"*.{host}"],
            "session_duration": "720h", "app_launcher_visible": False,
        })
        print("Access-app aangemaakt")
    policies = api("GET", f"{acc}/access/apps/{app['id']}/policies")
    for p in policies:  # alleen onze eigen regel mag bestaan
        api("DELETE", f"{acc}/access/apps/{app['id']}/policies/{p['id']}")
    api("POST", f"{acc}/access/apps/{app['id']}/policies", {
        "name": "Alleen eigenaar", "decision": "allow", "precedence": 1,
        "include": [{"email": {"email": args.email}}],
    })
    print(f"Alleen {args.email} mag inloggen")

    # 3. Uploaden
    env = {**os.environ, "CLOUDFLARE_ACCOUNT_ID": account, "WRANGLER_SEND_METRICS": "false",
           # wrangler wil altijd een token zien; bij een network secret vervangt de proxy hem
           "CLOUDFLARE_API_TOKEN": token or "via-proxy"}
    subprocess.run(["npx", "--yes", WRANGLER, "pages", "deploy", "site", "--project-name", args.project,
                    "--branch", "main", "--commit-dirty=true"], check=True, env=env)

    # 4. Controle: zonder login moet je naar Cloudflare Access
    req = urllib.request.Request(f"https://{host}/", method="GET")
    opener = urllib.request.build_opener(type("NoRedirect", (urllib.request.HTTPRedirectHandler,),
                                              {"redirect_request": lambda *a, **k: None}))
    try:
        r = opener.open(req, timeout=30)
        status, location = r.status, ""
    except urllib.error.HTTPError as e:
        status, location = e.code, e.headers.get("location", "")
    if status in (302, 303) and "cloudflareaccess.com" in location:
        print(f"Klaar en beveiligd: https://{host}")
    else:
        print(f"LET OP: verwachtte een login-doorverwijzing, kreeg {status} {location}")
        sys.exit(1)


if __name__ == "__main__":
    main()
