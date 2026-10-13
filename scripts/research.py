"""EXP-101: vorregistrierte Strategien gegen Benchmarks testen und Gates auswerten."""
from __future__ import annotations

import json
import sys
from functools import partial
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tbot import backtest, strategies  # noqa: E402
from tbot.data import load_universe, panel  # noqa: E402
from tbot.metrics import slice_equity, summarize  # noqa: E402


def evaluate(cfg: dict, data_dir: Path) -> dict:
    frames, reports = load_universe(data_dir, cfg["universe"])
    bad = [r for r in reports if not r.ok]
    if bad:
        raise SystemExit(f"Datenqualitätsgate nicht bestanden: {[(r.symbol, r.errors) for r in bad]}")
    opens, closes = panel(frames, cfg["universe"])
    ends = strategies.month_end_dates(closes.index)
    fns = {k: partial(strategies.signal, p=v) for k, v in cfg["strategies"].items()}
    fns.update({k: partial(strategies.constant, weights=v) for k, v in cfg["benchmarks"].items()})
    # gemeinsamer Start: erstes Monatsende, an dem ALLE Strategien ein Signal liefern
    dev_start = pd.Timestamp(cfg["periods"]["dev"][0])
    start = next(d for d in ends if d >= dev_start and all(fn(closes.loc[:d]) for fn in fns.values()))
    c = cfg["costs"]
    runs = {k: backtest.run(opens, closes, fn, slippage_bps=c["slippage_bps"], commission=c["commission_per_order"],
                            start=str(start.date())) for k, fn in fns.items()}
    periods = {"full": [str(start.date()), None], **cfg["periods"]}
    periods["dev"] = [str(start.date()), periods["dev"][1]]
    table = {k: {p: summarize(slice_equity(r.equity, *rng), r.trades) for p, rng in periods.items()}
             for k, r in runs.items()}
    for k, r in runs.items():
        table[k]["full"]["costs"] = r.costs
    return {"start": str(start.date()), "data": {r.symbol: [r.first, r.last, r.warnings] for r in reports},
            "metrics": table, "gates": gates(cfg, table), "last_weights": {
                k: {s: round(w, 4) for s, w in r.weights.iloc[-1].items() if w > 0} for k, r in runs.items()}}


def gates(cfg: dict, t: dict) -> dict:
    g = cfg["gate_to_paper"]
    b = g["benchmark"]
    out = {}
    for k in cfg["strategies"]:
        m, bm = t[k], t[b]
        checks = {
            "full_sharpe": m["full"]["sharpe"] - bm["full"]["sharpe"] >= g["full_period"]["min_sharpe_vs_benchmark"],
            "full_drawdown": abs(m["full"]["max_drawdown"]) <= g["full_period"]["max_drawdown_ratio_vs_benchmark"] * abs(bm["full"]["max_drawdown"]),
            "full_cagr_vs_60_40": m["full"]["cagr"] - t["60-40"]["full"]["cagr"] >= g["full_period"]["min_cagr_vs_60_40"],
        }
        for p in cfg["periods"]:
            checks[f"{p}_sharpe"] = m[p]["sharpe"] - bm[p]["sharpe"] >= g["each_subperiod"]["min_sharpe_vs_benchmark"]
        out[k] = {"passed": all(checks.values()), "checks": checks}
    passing = [k for k, v in out.items() if v["passed"]]
    out["_selected"] = max(passing, key=lambda k: t[k]["dev"]["sharpe"]) if passing else None
    return out


def to_markdown(res: dict) -> str:
    pct = lambda x: f"{x * 100:,.1f} %"  # noqa: E731
    lines = [f"# EXP-101 Ergebnis", "", f"Gemeinsamer Start: {res['start']}. Kosten: 5 bp Slippage je Seite.", ""]
    for p in ["full", "dev", "validation", "holdout"]:
        lines += [f"## {p}", "", "| Strategie | CAGR | Vol | Sharpe | Max DD | Schlechtester Monat | Orders |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for k, v in res["metrics"].items():
            m = v[p]
            lines.append(f"| {k} | {pct(m['cagr'])} | {pct(m['vol'])} | {m['sharpe']:.2f} | {pct(m['max_drawdown'])} | "
                         f"{pct(m['worst_month'])} | {m.get('orders', '')} |")
        lines.append("")
    lines += ["## Gates zu Papertrading", ""]
    for k, v in res["gates"].items():
        if k.startswith("_"):
            continue
        fails = [c for c, ok in v["checks"].items() if not ok]
        lines.append(f"- **{k}**: {'BESTANDEN' if v['passed'] else 'nicht bestanden – ' + ', '.join(fails)}")
    lines += ["", f"**Ausgewählt:** {res['gates']['_selected'] or 'keine Strategie'}", ""]
    lines += ["## Aktuelle Zielgewichte", ""] + [f"- {k}: {v}" for k, v in res["last_weights"].items()]
    return "\n".join(lines) + "\n"


def main() -> None:
    cfg = json.loads((ROOT / "config/research.json").read_text())
    res = evaluate(cfg, ROOT / "data/raw")
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    (out / "EXP-101.json").write_text(json.dumps(res, indent=2, default=float))
    (out / "EXP-101.md").write_text(to_markdown(res))
    print(to_markdown(res))


if __name__ == "__main__":
    main()
