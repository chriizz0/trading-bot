#!/bin/zsh
# EXP-201-Daten auf dem eigenen Mac laden (Dukascopy blockt GitHub-Server mit HTTP 202).
# Aufruf im Terminal:  zsh fetch_intraday_mac.sh
set -e
DIR="$HOME/Documents/20 Projekte/trading-bot-daten"
mkdir -p "$DIR" && cd "$DIR"
TO=$(date -v-1d +%F)
for pair in US500:usa500idxusd US100:usatechidxusd DE40:deuidxeur; do
  name=${pair%%:*}; id=${pair##*:}
  for side in bid ask; do
    [ -s "$name-$side.csv" ] && { echo "$name-$side vorhanden"; continue; }
    echo "Lade $name $side ..."
    npx --yes dukascopy-node@1 -s -i "$id" -from 2016-01-01 -to "$TO" -t m30 -p "$side" \
      -f csv -dir . -fn "$name-$side" -bs 10 -bp 500 -r 10 -rp 3000 -ch -chpath .cache
  done
done
ls -lh *.csv && echo "FERTIG – sag Claude Bescheid."
