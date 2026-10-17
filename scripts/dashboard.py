"""Sammelt alle Ergebnisse in docs/data.json für das Dashboard (GitHub Pages)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(p: str):
    f = ROOT / p
    return json.loads(f.read_text()) if f.exists() else None


def latest(folder: str):
    fs = sorted((ROOT / folder).glob("*.json"))
    return json.loads(fs[-1].read_text()) if fs else None


def main() -> None:
    claude, gpt = latest("predictions/exp401"), latest("predictions/exp401-chatgpt")
    cur = max([p["week_start"] for p in (claude, gpt) if p] or [""])
    rows = {}
    for arm, p in (("Claude", claude), ("ChatGPT", gpt)):
        if p and p["week_start"] == cur:
            for x in p["predictions"]:
                r = rows.setdefault(x["symbol"], {"symbol": x["symbol"]})
                r[arm] = x["p_up"]
                if x.get("trade"):
                    r[arm + "_trade"] = f'{x["trade"]["side"]} (Stop {x["trade"]["stop_pct"]:.1%}, Ziel {x["trade"]["target_pct"]:.1%})'
                if arm == "Claude":
                    r["reason"] = x.get("reason", "")
    data = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "history": [
            {"id": "EXP-101", "title": "ETF-Strategien monatlich", "verdict": "knapp gescheitert", "detail": "TREND-SPY: Sharpe 0,68 vs. SPY 0,66, Drawdown −25 % vs. −51 %, Rendite knapp unter 60/40"},
            {"id": "EXP-201", "title": "Intraday mit Index-CFDs", "verdict": "gescheitert", "detail": "Spread frisst 18–40 % der Bewegung; alle Kombinationen ≤ 0"},
            {"id": "EXP-301", "title": "Trendfolgen 12 Märkte mit Hebel", "verdict": "gescheitert", "detail": "Futures-Kosten Sharpe 0,27; mit CFD-Gebühren −4 % p.a."},
        ],
        "exp401": {"score": load("reports/exp401/score.json"), "week": cur, "rows": sorted(rows.values(), key=lambda r: r["symbol"])},
        "exp402": load("reports/exp402/score.json"),
    }
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs/data.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print("docs/data.json aktualisiert")


if __name__ == "__main__":
    main()
