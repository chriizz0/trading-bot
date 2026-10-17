"""EXP-401 Gegenspieler: ChatGPT bekommt denselben Snapshot und gibt Wochenprognosen im gleichen Format ab.
Läuft samstags in GitHub Actions nach dem Snapshot (Secret OPENAI_API_KEY)."""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tbot.llm import ask_openai, extract_json  # noqa: E402

PROMPT = """Du bist Aktienanalyst. Gib für die kommende Handelswoche (Einstieg Montag-Eröffnung, Ausstieg Freitag-Schluss)
für JEDEN Wert eine ehrlich kalibrierte Wahrscheinlichkeit p_up an, dass er am Freitag höher schließt als er am Montag eröffnet.
Optional ein Trade nur bei p_up >= 0.6 (long) oder <= 0.4 (short) mit stop_pct und target_pct (Dezimalzahlen, z. B. 0.03).
Nutze nur die folgenden Kennzahlen (Stand Freitag-Schluss) und dein Allgemeinwissen; erfinde keine Zahlen.

{table}

Antworte NUR mit JSON: {{"predictions": [{{"symbol": "...", "p_up": 0.55, "trade": null oder {{"side": "long|short", "stop_pct": 0.03, "target_pct": 0.04}}, "reason": "ein Satz"}}]}}"""


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY fehlt – ChatGPT-Arm übersprungen.")
        return 0
    cfg = json.loads((ROOT / "config/exp401.json").read_text())
    today = date.today()
    week = today + timedelta(days=(7 - today.weekday()) % 7 or 7)  # nächster Montag
    if week.isoformat() not in cfg["rounds"]:
        print(f"{week} ist keine Runde.")
        return 0
    out = ROOT / "predictions/exp401-chatgpt" / f"{week}.json"
    if out.exists():
        print("existiert schon")
        return 0
    snaps = sorted((ROOT / "reports/exp401").glob("snapshot-*.md"))
    table = snaps[-1].read_text()
    universe = cfg.get("universe_from_round2", cfg["universe"]) if week.isoformat() != cfg["rounds"][0] else cfg["universe"]
    data = extract_json(ask_openai(PROMPT.format(table=table)))
    preds = {p["symbol"]: p for p in data["predictions"] if p.get("symbol") in universe}
    clean = []
    for s in universe:
        p = preds.get(s, {"p_up": 0.5, "trade": None, "reason": "keine Angabe"})
        q = min(max(float(p.get("p_up", 0.5)), 0.0), 1.0)
        tr = p.get("trade")
        if tr and not ((q >= 0.6 and tr.get("side") == "long") or (q <= 0.4 and tr.get("side") == "short")):
            tr = None
        clean.append({"symbol": s, "p_up": q, "trade": tr, "reason": p.get("reason", "")})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"experiment": "EXP-401", "week_start": week.isoformat(), "analyst": "ChatGPT",
                               "model": os.environ.get("OPENAI_MODEL", "gpt-5"),
                               "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "inputs": [snaps[-1].name], "predictions": clean}, indent=2, ensure_ascii=False))
    print(f"ChatGPT-Prognosen gespeichert: {out.name}, fehlende Werte: {[s for s in universe if s not in preds]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
