"""Start de app:  python -m app"""

import logging
import os
import socket
import sys
import threading
import webbrowser


def _free_port(start=8000):
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if sys.platform != "win32":  # zelfde gedrag als uvicorn
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise SystemExit("Geen vrije poort gevonden")


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import uvicorn

    from .main import app, lan_ip

    port = _free_port(int(os.environ.get("FOTOSTUDIO_PORT", 8000)))
    local = f"http://localhost:{port}"
    ip = lan_ip()
    line = "=" * 60
    print(f"\n{line}\n  FOTOSTUDIO draait!\n")
    print(f"  Op deze computer:   {local}")
    if ip:
        print(f"  Op je telefoon:     http://{ip}:{port}")
        print("  (telefoon moet op hetzelfde wifi-netwerk zitten)")
    print("\n  Laat dit venster open zolang je de app gebruikt.")
    print(f"  Afsluiten: sluit dit venster of druk op Ctrl+C.\n{line}\n")

    if os.environ.get("FOTOSTUDIO_NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open(local)).start()
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
