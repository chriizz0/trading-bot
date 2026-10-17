"""EXP-401: Wochen-Snapshot (Technik) für Claudes Analyse und Auswertung der Prognosen.

  python scripts/exp401.py snapshot   → reports/exp401/snapshot-<Datum>.md
  python scripts/exp401.py score      → reports/exp401/SCORE.md
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config/exp401.json").read_text())
OUT = ROOT / "reports/exp401"
PRED = ROOT / "predictions/exp401"
COST = 0.001


def history(sym: str, start: str = "2024-01-01") -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(sym, start=start, auto_adjust=True, progress=False, multi_level_index=False)
    df.index = pd.DatetimeIndex(df.index).tz_localize(None)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


def rsi(c: pd.Series, n: int = 14) -> float:
    d = c.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / n).mean(), (-d.clip(upper=0)).ewm(alpha=1 / n).mean()
    return float(100 - 100 / (1 + up.iloc[-1] / dn.iloc[-1]))


def snapshot() -> None:
    rows = []
    for s in CFG["universe"]:
        d = history(s)
        c = d["Close"]
        tr = pd.concat([d["High"] - d["Low"], (d["High"] - c.shift()).abs(), (d["Low"] - c.shift()).abs()], axis=1).max(axis=1)
        r = lambda n: c.iloc[-1] / c.iloc[-1 - n] - 1  # noqa: E731
        rows.append({"Wert": s, "Datum": str(c.index[-1].date()), "Schluss": round(float(c.iloc[-1]), 2),
                     "1W %": round(r(5) * 100, 1), "1M %": round(r(21) * 100, 1), "3M %": round(r(63) * 100, 1),
                     "vs SMA20 %": round((c.iloc[-1] / c.tail(20).mean() - 1) * 100, 1),
                     "vs SMA50 %": round((c.iloc[-1] / c.tail(50).mean() - 1) * 100, 1),
                     "vs SMA200 %": round((c.iloc[-1] / c.tail(200).mean() - 1) * 100, 1),
                     "RSI14": round(rsi(c), 0), "ATR14 %": round(float(tr.tail(14).mean() / c.iloc[-1] * 100), 2),
                     "vom 52W-Hoch %": round((c.iloc[-1] / c.tail(252).max() - 1) * 100, 1),
                     "Vol/Ø20": round(float(d["Volume"].iloc[-1] / d["Volume"].tail(20).mean()), 2) if d["Volume"].tail(20).mean() > 0 else None})
    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    (OUT / f"snapshot-{today}.md").write_text(f"# EXP-401 Snapshot {today} (Daten bis Freitag-Schluss)\n\n" + df.to_markdown(index=False) + "\n")
    (OUT / "snapshot-latest.json").write_text(df.to_json(orient="records", indent=1, force_ascii=False))
    print(df.to_string(index=False))


def committed_at(path: Path) -> datetime | None:
    out = subprocess.run(["git", "log", "--diff-filter=A", "--format=%cI", "--", str(path)], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip().splitlines()
    return datetime.fromisoformat(out[-1]) if out else None


def simulate(d: pd.DataFrame, side: int, stop: float, target: float) -> float:
    entry = d["Open"].iloc[0]
    sp, tp = entry * (1 - side * stop), entry * (1 + side * target)
    for _, b in d.iterrows():
        if (side > 0 and b.Low <= sp) or (side < 0 and b.High >= sp):
            ex = min(b.Open, sp) if side > 0 else max(b.Open, sp)
            break
        if (side > 0 and b.High >= tp) or (side < 0 and b.Low <= tp):
            ex = tp
            break
    else:
        ex = d["Close"].iloc[-1]
    return (side * (ex / entry - 1) - COST) / stop


def score() -> None:
    rows, trades, notes = [], [], []
    for f in sorted(PRED.glob("*.json")):
        p = json.loads(f.read_text())
        week = pd.Timestamp(p["week_start"])
        t = committed_at(f)
        if t is None or t > datetime(week.year, week.month, week.day, 13, 30, tzinfo=timezone.utc):
            notes.append(f"{f.name}: nach Wochenbeginn committet → ungültig")
            continue
        end = week + pd.Timedelta(days=4)
        if pd.Timestamp(date.today()) <= end:
            notes.append(f"{f.name}: Woche läuft noch")
            continue
        for x in p["predictions"]:
            h = history(x["symbol"], str((week - pd.Timedelta(days=60)).date()))
            wk = h.loc[week:end]
            if wk.empty:
                continue
            up = float(wk["Close"].iloc[-1] > wk["Open"].iloc[0])
            prev = h.loc[:week - pd.Timedelta(days=1), "Close"]
            mom = float(prev.iloc[-1] / prev.iloc[-21] - 1 > 0)
            rows.append({"week": p["week_start"], "symbol": x["symbol"], "p": x["p_up"], "up": up, "mom": mom,
                         "ret": float(wk["Close"].iloc[-1] / wk["Open"].iloc[0] - 1)})
            tr = x.get("trade")
            if tr:
                side = 1 if tr["side"] == "long" else -1
                trades.append({"week": p["week_start"], "symbol": x["symbol"], "side": tr["side"],
                               "R": simulate(wk, side, tr["stop_pct"], tr["target_pct"])})
    L = ["# EXP-401 Zwischenstand – Claude als Analyst", "", f"Stand {date.today()}", ""]
    if rows:
        r = pd.DataFrame(rows)
        dec = r[r.p != 0.5]
        hit = float(((dec.p > 0.5) == (dec.up == 1)).mean()) if len(dec) else float("nan")
        brier = lambda q: float(((q - r.up) ** 2).mean())  # noqa: E731
        L += [f"- Prognosen ausgewertet: {len(r)} (Wochen: {r.week.nunique()})",
              f"- Trefferquote Richtung: {hit:.1%} (Ziel ≥ 55 %; Anteil steigender Werte: {r.up.mean():.0%})",
              f"- Brier Claude: {brier(r.p):.4f} · Münzwurf: 0,2500 · immer long 0,55: {brier(pd.Series(0.55, index=r.index)):.4f}"
              f" · Momentum: {brier(r.mom * 0.1 + 0.45):.4f} (kleiner = besser)", ""]
        per = r.assign(hit=(r.p > 0.5) == (r.up == 1)).groupby("week").agg(n=("hit", "size"), Treffer=("hit", "mean"))
        L += [per.to_markdown(), ""]
    if trades:
        t = pd.DataFrame(trades)
        L += [f"- Trade-Vorschläge: {len(t)}, Ø {t.R.mean():+.2f} R, Gewinner {float((t.R > 0).mean()):.0%}", "",
              t.round(2).to_markdown(index=False), ""]
    L += [f"- {n}" for n in notes]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "SCORE.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    {"snapshot": snapshot, "score": score}[sys.argv[1]]()
