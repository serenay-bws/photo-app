"""Paden en instellingen."""

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
DATA_DIR = Path(os.environ.get("FOTOSTUDIO_DATA", ROOT / "data"))
PHOTOS_DIR = DATA_DIR / "photos"
EXPORTS_DIR = DATA_DIR / "exports"
BIN_DIR = DATA_DIR / "bin"
PRESETS_FILE = DATA_DIR / "presets.json"
STATIC_DIR = APP_DIR / "static"
MODELS_DIR = APP_DIR / "models"

# Grootte van de preview die de browser bewerkt
PREVIEW_LONG = 1600
THUMB_LONG = 360
# Na upscalen nooit groter dan dit (lange zijde, in pixels)
MAX_UPSCALE_LONG = int(os.environ.get("FOTOSTUDIO_MAX_SIDE", 8192))
JPEG_QUALITY = 95

for _d in (PHOTOS_DIR, EXPORTS_DIR, BIN_DIR):
    _d.mkdir(parents=True, exist_ok=True)
