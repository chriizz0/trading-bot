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
ARMS = {"Claude": ROOT / "predictions/exp401", "ChatGPT": ROOT / "predictions/exp401-chatgpt"}
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
    for s in CFG.get("universe_from_round2", CFG["universe"]):
        try:
            d = history(s)
            assert len(d) > 210
        except Exception as e:  # noqa: BLE001
            rows.append({"Wert": s, "Datum": f"FEHLT ({type(e).__name__})"})
            continue
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
    name = OUT / f"snapshot-{today}.md"
    if name.exists():  # nie einen alten Snapshot überschreiben (Prognose-Eingaben bleiben nachvollziehbar)
        name = OUT / f"snapshot-{datetime.now(timezone.utc):%Y-%m-%dT%H%M}.md"
    name.write_text(f"# EXP-401 Snapshot {today} (Daten bis Freitag-Schluss)\n\n" + df.to_markdown(index=False) + "\n")
    (OUT / "snapshot-latest.json").write_text(df.to_json(orient="records", indent=1, force_ascii=False))
    print(df.to_string(index=False))


def bench_of(sym: str) -> str:
    b = CFG["benchmarks"]
    if sym.endswith(".DE"):
        return b["DE"]
    if "." in sym:
        return b["EU"]
    return b["US"]


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


_HIST: dict = {}


def hist_cached(sym: str, start: str) -> pd.DataFrame:
    if sym not in _HIST:
        _HIST[sym] = history(sym, "2026-06-01")
    return _HIST[sym].loc[start:]


def evaluate(arm: str, folder: Path) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    rows, trades, notes = [], [], []
    for f in sorted(folder.glob("*.json")):
        p = json.loads(f.read_text())
        week = pd.Timestamp(p["week_start"])
        t = committed_at(f)
        if t is None or t > datetime(week.year, week.month, week.day, 0, 0, tzinfo=timezone.utc):  # vor Xetra- und US-Eröffnung
            notes.append(f"{arm} {f.name}: nicht vor Montag 00:00 UTC committet → ungültig")
            continue
        end = week + pd.Timedelta(days=4)
        if pd.Timestamp(date.today()) <= end:
            notes.append(f"{arm} {f.name}: Woche läuft noch")
            continue
        for x in p["predictions"]:
            h = hist_cached(x["symbol"], str((week - pd.Timedelta(days=60)).date()))
            wk = h.loc[week:end]
            if wk.empty:
                continue
            ret = float(wk["Close"].iloc[-1] / wk["Open"].iloc[0] - 1)
            bk = hist_cached(bench_of(x["symbol"]), str(week.date())).loc[:end]
            bret = float(bk["Close"].iloc[-1] / bk["Open"].iloc[0] - 1) if len(bk) else float("nan")
            prev = h.loc[:week - pd.Timedelta(days=1), "Close"]
            rows.append({"arm": arm, "week": p["week_start"], "symbol": x["symbol"], "p": float(x["p_up"]),
                         "up": float(ret > 0), "mom": float(prev.iloc[-1] / prev.iloc[-21] - 1 > 0),
                         "ret": ret, "alpha": ret - bret})
            tr = x.get("trade")
            if tr:
                side = 1 if tr["side"] == "long" else -1
                trades.append({"arm": arm, "week": p["week_start"], "symbol": x["symbol"], "side": tr["side"],
                               "R": simulate(wk, side, tr["stop_pct"], tr["target_pct"])})
    return pd.DataFrame(rows), pd.DataFrame(trades), notes


def metrics(r: pd.DataFrame, t: pd.DataFrame) -> dict:
    dec = r[r.p != 0.5]
    out = {"n": int(len(r)), "weeks": int(r.week.nunique()),
           "hit_rate": float(((dec.p > 0.5) == (dec.up == 1)).mean()) if len(dec) else None,
           "share_up": float(r.up.mean()),
           "brier": float(((r.p - r.up) ** 2).mean()),
           "brier_coin": 0.25, "brier_always_long": float(((0.55 - r.up) ** 2).mean()),
           "brier_momentum": float(((r.mom * 0.1 + 0.45 - r.up) ** 2).mean())}
    x = r[~r.symbol.isin(CFG["not_in_ic"])].dropna(subset=["alpha"])
    wk = [g for _, g in x.groupby("week") if g.p.nunique() > 1]
    if wk:
        ics = [g.p.rank().corr(g.alpha.rank()) for g in wk]
        rng = np.random.default_rng(0)
        null = [np.mean([pd.Series(rng.permutation(g.p.values)).rank().corr(g.alpha.rank().reset_index(drop=True))
                         for g in wk]) for _ in range(2000)]
        ls = [g.loc[g.p > 0.5, "alpha"].mean() - g.loc[g.p < 0.5, "alpha"].mean() for g in wk]
        out.update({"ic_mean": float(np.mean(ics)), "ic_by_week": dict(zip([g.week.iloc[0] for g in wk], map(float, ics))),
                    "perm_p": float(np.mean(np.array(null) >= np.mean(ics))),
                    "ls_by_week": dict(zip([g.week.iloc[0] for g in wk], map(float, ls)))})
    bins = r.p.map(lambda q: "≤0,4" if q <= 0.4 else "0,4–0,5" if q < 0.5 else "0,5" if q == 0.5 else "0,5–0,6" if q < 0.6 else "≥0,6")
    out["calibration"] = r.groupby(bins).agg(n=("up", "size"), p=("p", "mean"), up=("up", "mean")).round(3).reset_index(names="bin").to_dict("records")
    if len(t):
        out.update({"trades": int(len(t)), "trade_mean_R": float(t.R.mean()), "trade_win": float((t.R > 0).mean())})
    return out


def score() -> None:
    allr, allt, notes, res = [], [], [], {}
    for arm, folder in ARMS.items():
        if not folder.exists():
            continue
        r, t, n = evaluate(arm, folder)
        notes += n
        if len(r):
            res[arm] = metrics(r, t)
            allr.append(r)
            if len(t):
                allt.append(t)
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {"updated": str(date.today()), "arms": res, "notes": notes,
               "predictions": pd.concat(allr).round(5).to_dict("records") if allr else [],
               "trades": pd.concat(allt).round(3).to_dict("records") if allt else []}
    (OUT / "score.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str))
    L = ["# EXP-401 Zwischenstand – KI als Analyst", "", f"Stand {date.today()}", ""]
    for arm, m in res.items():
        L += [f"## {arm}", "", "**Prognosegüte**", "",
              f"- Prognosen: {m['n']} in {m['weeks']} Wochen · Trefferquote {m['hit_rate']:.1%} (Ziel ≥ 55 %; Anteil steigender Werte {m['share_up']:.0%})",
              f"- Brier {m['brier']:.4f} · Münzwurf 0,2500 · immer long {m['brier_always_long']:.4f} · Momentum {m['brier_momentum']:.4f} (kleiner = besser)"]
        if "ic_mean" in m:
            L.append(f"- Information Coefficient Ø {m['ic_mean']:+.3f} (Permutationstest p = {m['perm_p']:.2f}) · "
                     f"Long-Short kumuliert {sum(m['ls_by_week'].values())*100:+.2f} %")
        if "trades" in m:
            L += ["", "**Simulierte Trades** (Tageskerzen, 0,1 % Kosten, keine echte Ausführung – getrennt von der Prognosegüte lesen)", ""]
            L.append(f"- Trades: {m['trades']}, Ø {m['trade_mean_R']:+.2f} R, Gewinner {m['trade_win']:.0%}")
        L += ["", pd.DataFrame(m["calibration"]).to_markdown(index=False), ""]
    L += [f"- {n}" for n in notes]
    (OUT / "SCORE.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    {"snapshot": snapshot, "score": score}[sys.argv[1]]()
