from __future__ import annotations

import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load_cfg() -> tuple[dict, dict]:
    research = json.loads((ROOT / "config/research.json").read_text())
    live = json.loads((ROOT / "config/live.json").read_text())
    return research, live


def strategy_params(research: dict, name: str) -> dict:
    if name == "PIPELINE-TEST":
        return {"type": "constant", "weights": research["benchmarks"]["60-40"]}
    return research["strategies"][name]


def trading_days(broker, start: date, end: date) -> list[date]:
    return [date.fromisoformat(d["date"]) for d in broker.calendar(start.isoformat(), end.isoformat())]


def market_today(broker) -> date:
    return date.fromisoformat(broker.clock()["timestamp"][:10])  # Börsenzeit (ET)


def is_month_end(broker, today: date) -> bool:
    days = [d for d in trading_days(broker, today, today + timedelta(days=12)) if d > today]
    return bool(days) and days[0].month != today.month


def peak_equity(path: Path, current: float) -> float:
    if not path.exists():
        return current
    with path.open() as f:
        vals = [float(r["equity"]) for r in csv.DictReader(f)]
    return max(vals + [current])


def append_csv(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)
