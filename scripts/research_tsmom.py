"""EXP-301 auswerten (Daten via yfinance, läuft in GitHub Actions)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from tbot import tsmom  # noqa: E402
from tbot.data import load_csv, validate  # noqa: E402


def load(cfg: dict, data_dir: Path) -> tuple[pd.DataFrame, pd.Series, dict]:
    syms = list(cfg["universe"]) + [cfg["cash"]]
    closes, quality = {}, {}
    for s in syms:
        df = load_csv(data_dir / f"{s}.csv")
        rep = validate(df, s)
        quality[s] = {"first": rep.first, "last": rep.last, "errors": rep.errors, "warnings": rep.warnings}
        if not rep.ok:
            raise SystemExit(f"Datenfehler {s}: {rep.errors}")
        closes[s] = df["adj_close"]
    px = pd.DataFrame(closes).loc[cfg["data"]["start"]:]
    rets = px.pct_change().iloc[1:]
    rf = rets.pop(cfg["cash"]).fillna(0.0)
    return rets, rf, quality


def period_slice(df: pd.DataFrame, a, b) -> pd.DataFrame:
    return df.loc[(a or df.index[0]):(b or df.index[-1])]


def main() -> None:
    cfg = json.loads((ROOT / "config/exp301.json").read_text())
    rets, rf, quality = load(cfg, ROOT / "data/raw")
    spy_ex = rets["SPY"] - rf
    p = cfg["strategy"]
    variants = {"TSMOM-HOP": [21, 63, 252], "TSMOM-12M": [252]}
    first_valid = None
    res, gates = {"data": quality, "results": {}}, {}
    for vname, lbs in variants.items():
        w = tsmom.weights(rets, rf, p, lbs)
        start = w.abs().sum(axis=1).gt(0).idxmax()
        first_valid = first_valid or start
        for cname, cm in cfg["cost_models"].items():
            r = tsmom.run(rets, rf, w, cm["trade_cost_bps"]["default"], cm["financing_markup_pa"]).loc[start:]
            per = {"full": [None, None], **cfg["periods"]}
            res["results"][f"{vname}/{cname}"] = {k: tsmom.stats(period_slice(r, *v), spy_ex) for k, v in per.items()}
        res["results"][f"{vname}/letzte Gewichte"] = {k: round(v, 3) for k, v in w.iloc[-1].items() if abs(v) > 1e-4}
    bh = pd.DataFrame({"excess": spy_ex, "total": rets["SPY"], "gross_excess": spy_ex, "trade_cost": 0.0,
                       "financing": 0.0, "turnover": 0.0, "gross_leverage": 1.0}).loc[first_valid:]
    res["results"]["SPY Buy&Hold"] = {k: tsmom.stats(period_slice(bh, *v)) for k, v in
                                      {"full": [None, None], **cfg["periods"]}.items()}
    g = cfg["gate_to_paper"]
    for cname in cfg["cost_models"]:
        m = res["results"][f"TSMOM-HOP/{cname}"]
        checks = {"full_sharpe": m["full"]["sharpe"] >= g["full"]["min_sharpe"],
                  "full_drawdown": m["full"]["max_drawdown"] >= -g["full"]["max_drawdown"],
                  "full_corr_spy": m["full"]["corr_spy"] <= g["full"]["max_corr_to_spy"]}
        checks.update({f"{k}_sharpe": m[k]["sharpe"] >= g["each_period"]["min_sharpe"] for k in cfg["periods"]})
        gates[cname] = {"passed": all(checks.values()), "checks": checks}
    res["gates"] = gates
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    (out / "EXP-301.json").write_text(json.dumps(res, indent=2, default=str))
    L = ["# EXP-301 Ergebnis – Trendfolgen (TSMOM)", "", f"Start der Auswertung: {first_valid.date()}", ""]
    for per in ["full", "dev", "validation", "holdout"]:
        L += [f"## {per}", "", "| Variante | CAGR gesamt | Vol | Sharpe | Max DD | Ø Hebel | Kosten p.a. | Korr. SPY |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for k, v in res["results"].items():
            if "Gewichte" in k or not v.get(per):
                continue
            s = v[per]
            L.append(f"| {k} | {s['cagr_total']*100:.1f} % | {s['vol']*100:.1f} % | {s['sharpe']:.2f} | "
                     f"{s['max_drawdown']*100:.1f} % | {s['avg_gross_leverage']:.2f} | {s['cost_pa']*100:.2f} % | "
                     f"{s.get('corr_spy', float('nan')):.2f} |")
        L.append("")
    L += ["## Gate zu Paper (TSMOM-HOP)", ""]
    for c, v in gates.items():
        fails = [k for k, ok in v["checks"].items() if not ok]
        L.append(f"- **{c}**: {'BESTANDEN' if v['passed'] else 'nein – ' + ', '.join(fails)}")
    L += ["", "## Aktuelle Zielgewichte TSMOM-HOP", "", str(res["results"]["TSMOM-HOP/letzte Gewichte"])]
    (out / "EXP-301.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
