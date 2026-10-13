"""EXP-201 auswerten: 3 Strategien x 3 Index-CFDs, Gates laut config/exp201.json."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tbot import istrats  # noqa: E402
from tbot.ibt import simulate, stats  # noqa: E402
from tbot.intraday import load_mid, session_info, to_hourly  # noqa: E402


def split(trades: pd.DataFrame, periods: dict) -> dict[str, pd.DataFrame]:
    out = {"full": trades}
    if trades.empty:
        return {k: trades for k in ["full", *periods]}
    day = trades["entry_time"].dt.tz_convert("UTC").dt.tz_localize(None)
    for k, (a, b) in periods.items():
        m = pd.Series(True, index=trades.index)
        if a:
            m &= day >= pd.Timestamp(a)
        if b:
            m &= day < pd.Timestamp(b) + pd.Timedelta(days=1)
        out[k] = trades[m]
    return out


def gate(s: dict, g: dict) -> dict:
    dev, val, hold, full = s["dev"], s["validation"], s["holdout"], s["full"]
    ok = lambda x: x.get("trades", 0) > 0  # noqa: E731
    return {
        "dev_trades": dev.get("trades", 0) >= g["dev"]["min_trades"],
        "dev_t_stat": ok(dev) and dev["t_stat"] >= g["dev"]["min_t_stat"],
        "dev_profit_factor": ok(dev) and dev["profit_factor"] >= g["dev"]["min_profit_factor"],
        "validation_mean": ok(val) and val["mean_ret"] > g["validation"]["min_mean_net"],
        "validation_profit_factor": ok(val) and val["profit_factor"] >= g["validation"]["min_profit_factor"],
        "holdout_mean": ok(hold) and hold["mean_ret"] > g["holdout"]["min_mean_net"],
        "holdout_profit_factor": ok(hold) and hold["profit_factor"] >= g["holdout"]["min_profit_factor"],
        "full_drawdown": ok(full) and full["max_drawdown"] >= -g["full"]["max_drawdown"],
    }


def run(cfg: dict, data_dir: Path) -> dict:
    res = {"experiment": cfg["experiment_id"], "data": {}, "results": {}}
    for name, inst in cfg["instruments"].items():
        bars, errors = load_mid(data_dir, name)
        info = session_info(bars, inst, cfg["quality_gate"]["min_session_slot_coverage_per_day"])
        res["data"][name] = {"bars": len(bars), "first": str(bars.index[0]), "last": str(bars.index[-1]),
                             "errors": errors, "session_days": int(len(info)), "good_days": int(info["good"].sum())}
        if errors:
            continue
        good = set(info.index[info["good"]])
        hourly = to_hourly(bars)
        P = cfg["strategies"]
        runs = {
            "IMOM": (bars, istrats.imom(bars, info, P["IMOM"]), 30),
            "IBS": (bars, istrats.ibs(bars, info, P["IBS"]), 30),
            "DONCH": (hourly, istrats.donch(hourly, good, inst["tz"], P["DONCH"]), 60),
        }
        for sname, (b, sigs, mins) in runs.items():
            trades = simulate(b, sigs, inst, cfg["costs"], cfg["risk"], bar_minutes=mins)
            parts = split(trades, cfg["periods"])
            st = {k: stats(v) for k, v in parts.items()}
            checks = gate(st, cfg["gate_to_demo"])
            key = f"{sname}/{name}"
            res["results"][key] = {"stats": st, "checks": checks, "passed": all(checks.values())}
            out = ROOT / "reports/exp201"
            out.mkdir(parents=True, exist_ok=True)
            trades.to_csv(out / f"{sname}-{name}.csv", index=False)
    res["passed"] = [k for k, v in res["results"].items() if v["passed"]]
    return res


def markdown(res: dict) -> str:
    f = lambda x, p=2: "–" if x is None or x != x else f"{x:.{p}f}"  # noqa: E731
    L = [f"# {res['experiment']} Ergebnis", "", "## Daten", ""]
    for k, d in res["data"].items():
        L.append(f"- {k}: {d['bars']} Kerzen {d['first'][:10]}–{d['last'][:10]}, "
                 f"{d['good_days']}/{d['session_days']} Sitzungstage geprüft ok{', FEHLER: ' + '; '.join(d['errors']) if d['errors'] else ''}")
    for p in ["full", "dev", "validation", "holdout"]:
        L += ["", f"## {p}", "", "| Kombi | Trades | Ø Netto/Trade | t | PF | Trefferq. | Gesamt | Max DD | Ø Halten h | Kosten/|Brutto| |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for k, v in res["results"].items():
            s = v["stats"][p]
            if not s.get("trades"):
                L.append(f"| {k} | 0 | | | | | | | | |")
                continue
            L.append(f"| {k} | {s['trades']} | {s['mean_ret'] * 100:.3f} % | {f(s['t_stat'])} | {f(s['profit_factor'])} | "
                     f"{s['win_rate'] * 100:.0f} % | {s['total_return'] * 100:.1f} % | {s['max_drawdown'] * 100:.1f} % | "
                     f"{f(s['avg_hold_h'], 1)} | {s['cost_share_of_gross_abs'] * 100:.0f} % |")
    L += ["", "## Gates zu Demo", ""]
    for k, v in res["results"].items():
        fails = [c for c, ok in v["checks"].items() if not ok]
        L.append(f"- **{k}**: {'BESTANDEN' if v['passed'] else 'nein – ' + ', '.join(fails)}")
    L += ["", f"**Bestanden:** {', '.join(res['passed']) or 'keine Kombination'}"]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data/intraday"))
    a = ap.parse_args()
    cfg = json.loads((ROOT / "config/exp201.json").read_text())
    res = run(cfg, Path(a.data))
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports/EXP-201.json").write_text(json.dumps(res, indent=2, default=str))
    md = markdown(res)
    (ROOT / "reports/EXP-201.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
