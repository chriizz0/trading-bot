#!/bin/zsh
# EXP-201 auf dem Mac: Daten laden (fortsetzbar), auswerten, Ergebnis pushen.
# Aufruf im Ordner trading-bot:  zsh scripts/fetch_intraday_mac.sh
set -e
cd "$(dirname "$0")/.."
git pull -q
PY=.venv/bin/python; [ -x "$PY" ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
$PY scripts/fetch_dukascopy.py || { echo "Abruf unvollständig – Skript einfach nochmal starten."; exit 1; }
$PY -m unittest discover -s tests -q
$PY scripts/research_intraday.py | tail -40
git add reports/EXP-201.md reports/EXP-201.json reports/exp201
git commit -qm "research: EXP-201 Ergebnis (Dukascopy, lokal geladen)" && git push -q && echo "FERTIG – Ergebnis gepusht."
