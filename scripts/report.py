"""Wöchentlicher Paper-Bericht: echtes Paper-Depot vs. Schattendepot (Bot ohne
Claude-Veto, simuliert) vs. Benchmark. Misst, ob Claudes Prüfung etwas bringt."""
from __future__ import annotations

import csv
import json
from datetime import date, timedelta

import pandas as pd
from common import ROOT, load_cfg, strategy_params

from tbot import backtest, strategies
from tbot.data import load_csv, panel
from tbot.metrics import summarize


def main() -> int:
    research, live = load_cfg()
    eq_path = ROOT / "journal/equity.csv"
    if not live["strategy"] or not eq_path.exists():
        print("Noch kein Paper-Verlauf.")
        return 0
    with eq_path.open() as f:
        rows = list(csv.DictReader(f))
    actual = pd.Series({pd.Timestamp(r["date"]): float(r["equity"]) for r in rows}).sort_index()
    p = strategy_params(research, live["strategy"])
    syms = sorted(set(strategies.symbols_of(p)) | {"SPY"})
    from fetch_data import fetch
    start = actual.index[0].date()
    tmp = ROOT / "data/live"
    tmp.mkdir(parents=True, exist_ok=True)
    frames = {}
    for s in syms:
        fetch(s, (start - timedelta(days=500)).isoformat()).to_csv(tmp / f"{s}.csv")
        frames[s] = load_csv(tmp / f"{s}.csv")
    opens, closes = panel(frames, syms)
    # Schattendepot: startet am ersten Paper-Tag mit dem aktuellen Ziel, danach monatlich
    ends = strategies.month_end_dates(closes.index)
    first = closes.index[closes.index >= actual.index[0]][0]
    rebal = pd.DatetimeIndex([first]).append(ends[ends > first])
    sig = lambda h: strategies.current_target(h, p, h.index[-1] in set(ends))[1]  # noqa: E731
    shadow = backtest.run(opens, closes, sig, initial=actual.iloc[0], rebalance_dates=rebal,
                          slippage_bps=research["costs"]["slippage_bps"]).equity
    bench = actual.iloc[0] * closes["SPY"].loc[first:] / closes["SPY"].loc[first]
    res = {k: summarize(v) for k, v in {"paper": actual, "schatten_ohne_veto": shadow, "SPY": bench}.items()}
    lines = [f"# Paper-Status {date.today()}", "", f"Strategie: {live['strategy']} · Start {first.date()}", "",
             "| Depot | Rendite | Max DD |", "|---|---:|---:|"]
    for k, m in res.items():
        if m:
            lines.append(f"| {k} | {m['total_return'] * 100:.2f} % | {m['max_drawdown'] * 100:.2f} % |")
    gap = (res["paper"].get("total_return", 0) - res["schatten_ohne_veto"].get("total_return", 0)) * 100
    lines += ["", f"Abweichung Paper vs. Schatten: {gap:+.2f} Prozentpunkte "
              f"(Gate für Echtgeld: max. ±{research['gate_to_live']['max_abs_return_gap_vs_shadow_pp']} pp)."]
    (ROOT / "reports/paper-status.md").write_text("\n".join(lines) + "\n")
    (ROOT / "reports/paper-status.json").write_text(json.dumps(res, indent=2, default=float))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
