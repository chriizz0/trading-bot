#!/usr/bin/env bash
# Ergebnisse des Laufs zurück ins Repo schreiben (mit Rebase gegen parallele Läufe)
set -euo pipefail
git config user.name "trading-bot"
git config user.email "trading-bot@users.noreply.github.com"
existing=(); for p in "$@"; do [ -e "$p" ] && existing+=("$p"); done
[ ${#existing[@]} -eq 0 ] && { echo "nichts zu committen"; exit 0; }
git add -A -- "${existing[@]}"
git diff --cached --quiet && { echo "nichts zu committen"; exit 0; }
git commit -m "$COMMIT_MSG"
for i in 1 2 3; do git pull --rebase -q && git push -q && exit 0; sleep 5; done
exit 1
