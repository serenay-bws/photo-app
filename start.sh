#!/usr/bin/env bash
# Start Fotostudio (macOS / Linux). Installeert de eerste keer alles automatisch.
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  echo ""
  echo "  Eenmalige installatie (kan een paar minuten duren)..."
  echo ""
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  else
    wget -qO- https://astral.sh/uv/install.sh | sh
  fi
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "  Installatie mislukt. Controleer je internetverbinding en probeer opnieuw."
  read -r -p "  Druk op Enter om te sluiten..." _
  exit 1
fi

uv run --no-dev python -m app
status=$?
if [ $status -ne 0 ] && [ $status -ne 130 ]; then
  echo ""
  echo "  Er ging iets mis (foutcode $status). Maak een screenshot van dit venster als je hulp vraagt."
  read -r -p "  Druk op Enter om te sluiten..." _
fi
