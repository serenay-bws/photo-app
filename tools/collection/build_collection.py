"""Zet fit-resultaten om naar app/presets_collection.json.

Werkwijze (voor de ontwikkelaar, eenmalig):
  1. productafbeeldingen met voor/na-voorbeelden downloaden
  2. extract_pairs.py: voor- en na-paneel uitsnijden
  3. fit_pack.py: de app-instellingen zoeken die "voor" het best in "na" veranderen
     (scipy nodig: uv pip install scipy)
  4. dit script: resultaten (results.json + all.json) -> presets_collection.json

Gebruik: python tools/collection/build_collection.py results.json all.json
"""

import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "app" / "presets_collection.json"
# packs die al als Basis-preset bestaan (Dark Luxe / Gym Bronze) worden daar bijgewerkt
SEPARATE = {"dark-moody-presets": "dark-luxe", "gym-presets": "gym-bronze"}


def nice_name(title):
    name = re.sub(r"\b(lightroom|presets?|pack|free)\b", "", title, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip(" -&")
    return " ".join(w if w.isupper() else w[:1].upper() + w[1:] for w in name.split()) or title


def main():
    results = json.load(open(sys.argv[1]))
    titles = {p["handle"]: p["title"] for p in json.load(open(sys.argv[2]))["products"]}
    items, updates = [], {}
    for handle, r in sorted(results.items(), key=lambda kv: titles.get(kv[0], kv[0])):
        if not r or "params" not in r:
            continue
        # alleen looks die het voorbeeld echt benaderen
        if r["rmse_after"] > 0.6 * r["rmse_before"] or r["pairs"] < 2:
            print("overgeslagen:", handle, r.get("rmse_before"), r.get("rmse_after"))
            continue
        if handle in SEPARATE:
            updates[SEPARATE[handle]] = r["params"]
            continue
        name = nice_name(titles.get(handle, handle))
        short = "".join(w[0] for w in re.findall(r"\w+", name))[:2].upper()
        items.append({"id": f"col-{handle}", "name": name, "short": short, "params": r["params"],
                      "fit": {"pairs": r["pairs"], "rmse_before": r["rmse_before"], "rmse_after": r["rmse_after"]}})
    OUT.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(items)} presets -> {OUT}")
    print("Basis-updates:", json.dumps(updates))


if __name__ == "__main__":
    main()
