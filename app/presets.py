"""Ingebouwde presets en eigen (door de gebruiker opgeslagen) presets."""

import json
import re
import threading
import uuid

from .config import PRESETS_FILE
from .edits import clean_params

BUILTIN = [
    {
        "id": "moody-dark",
        "name": "Moody Dark",
        "short": "MD",
        "params": {
            "exposure": -22, "contrast": 18, "highlights": -50, "shadows": -12,
            "blacks": -28, "saturation": -38, "temperature": -6, "tint": 2,
            "grain": 32, "vignette": 50, "sharpness": 10, "fade": 0,
            "split_shadow": 22, "split_shadow_hue": 200,
            "split_highlight": 12, "split_highlight_hue": 35,
        },
    },
    {
        "id": "clean-bright",
        "name": "Clean Bright",
        "short": "CB",
        "params": {
            "exposure": 22, "contrast": -8, "highlights": -25, "shadows": 30,
            "blacks": 8, "saturation": -6, "temperature": 4, "tint": 0,
            "grain": 0, "vignette": 0, "sharpness": 15, "fade": 6,
            "split_highlight": 6, "split_highlight_hue": 45,
        },
    },
    {
        "id": "film-warm",
        "name": "Film Warm",
        "short": "FW",
        "params": {
            "exposure": 4, "contrast": 10, "highlights": -28, "shadows": 10,
            "blacks": 0, "saturation": -12, "temperature": 28, "tint": 6,
            "grain": 42, "vignette": 22, "sharpness": 0, "fade": 28,
            "split_shadow": 16, "split_shadow_hue": 28,
            "split_highlight": 20, "split_highlight_hue": 45,
        },
    },
    {
        "id": "cool-grey",
        "name": "Cool Grey",
        "short": "CG",
        "params": {
            "exposure": 0, "contrast": 6, "highlights": -22, "shadows": 12,
            "blacks": -6, "saturation": -52, "temperature": -26, "tint": -4,
            "grain": 10, "vignette": 12, "sharpness": 20, "fade": 14,
            "split_shadow": 20, "split_shadow_hue": 210,
        },
    },
    {
        "id": "bw-contrast",
        "name": "B&W Contrast",
        "short": "BW",
        "params": {
            "exposure": 0, "contrast": 45, "highlights": -12, "shadows": -10,
            "blacks": -30, "saturation": -100, "temperature": 0, "tint": 0,
            "grain": 25, "vignette": 28, "sharpness": 22, "fade": 0,
        },
    },
    {
        "id": "soft-matte",
        "name": "Soft Matte",
        "short": "SM",
        "params": {
            "exposure": 8, "contrast": -12, "highlights": -30, "shadows": 18,
            "blacks": 0, "saturation": -20, "temperature": 8, "tint": 4,
            "grain": 14, "vignette": 8, "sharpness": 5, "fade": 40,
            "split_shadow": 12, "split_shadow_hue": 320,
            "split_highlight": 10, "split_highlight_hue": 30,
        },
    },
    {
        # Nagebouwd op basis van voor/na-voorbeelden van een "dark moody" Lightroom-pack:
        # vooral ~2 stops donkerder, licht gedempte kleuren, huid iets lichter gehouden.
        "id": "dark-luxe",
        "name": "Dark Luxe",
        "short": "DL",
        "params": {
            "exposure": -100, "contrast": 6, "highlights": 0, "shadows": -2,
            "blacks": -14, "saturation": -11, "temperature": 6, "tint": 12,
            "grain": 0, "vignette": 7, "sharpness": 0, "fade": 0,
            "orange_lum": 19,
        },
    },
    {
        # Nagebouwd op basis van voor/na-voorbeelden van een "gym" Lightroom-pack:
        # donker met diepe zwarten, de huid wordt juist opgelicht en bronzer (kleurtinten).
        "id": "gym-bronze",
        "name": "Gym Bronze",
        "short": "GB",
        "params": {
            "exposure": -60, "contrast": 17, "highlights": 68, "shadows": 17,
            "blacks": -100, "saturation": -25, "temperature": 18, "tint": 10,
            "grain": 0, "vignette": 5, "sharpness": 10, "fade": 0,
            "orange_sat": 22, "orange_lum": 60,
            "split_shadow": 18, "split_shadow_hue": 198,
            "split_highlight": 18, "split_highlight_hue": 95,
        },
    },
]

for _p in BUILTIN:
    _p["params"] = clean_params(_p["params"])
    _p["builtin"] = True

_lock = threading.Lock()


def _load_custom():
    if not PRESETS_FILE.exists():
        return []
    try:
        data = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
        return [p for p in data if isinstance(p, dict) and "id" in p and "params" in p]
    except (OSError, ValueError):
        return []


def _save_custom(items):
    PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PRESETS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PRESETS_FILE)


def all_presets():
    custom = []
    for p in _load_custom():
        custom.append(
            {
                "id": p["id"],
                "name": p.get("name", "Eigen preset"),
                "short": p.get("short") or _short(p.get("name", "")),
                "params": clean_params(p["params"]),
                "builtin": False,
            }
        )
    return BUILTIN + custom


def presets_by_id():
    return {p["id"]: p for p in all_presets()}


def _short(name):
    letters = [w[0] for w in re.findall(r"\w+", name)]
    return ("".join(letters[:2]) or name[:2] or "P").upper()


def add_custom(name, params):
    name = (name or "").strip()[:40] or "Mijn preset"
    item = {
        "id": "custom-" + uuid.uuid4().hex[:8],
        "name": name,
        "short": _short(name),
        "params": clean_params(params),
    }
    with _lock:
        items = _load_custom()
        items.append(item)
        _save_custom(items)
    return {**item, "builtin": False}


def delete_custom(preset_id):
    with _lock:
        items = _load_custom()
        new = [p for p in items if p["id"] != preset_id]
        if len(new) == len(items):
            return False
        _save_custom(new)
    return True
