"""Nach US-Börsenschluss: Daten holen, Signal rechnen, Order-Vorschlag schreiben.
Es wird NICHTS gehandelt. Ausführung erst nach Claude-Review (execute.py)."""
from __future__ import annotations

import json
from datetime import timedelta

from common import ROOT, append_csv, is_month_end, load_cfg, market_today, peak_equity, strategy_params

from tbot import strategies
from tbot.broker import Alpaca
from tbot.data import load_csv, panel, validate
from tbot.live import build_orders, canonical_hash


def main() -> int:
    research, live = load_cfg()
    name = live["strategy"]
    if not name:
        print("Keine freigegebene Strategie in config/live.json – nichts zu tun.")
        return 0
    p = strategy_params(research, name)
    syms = strategies.symbols_of(p)
    broker = Alpaca()
    today = market_today(broker)
    cal = broker.calendar(today.isoformat(), today.isoformat())
    if not cal or cal[0]["date"] != today.isoformat():
        print(f"{today}: kein Handelstag.")
        return 0
    month_end = is_month_end(broker, today)

    from fetch_data import fetch
    frames, quality = {}, {}
    tmp = ROOT / "data/live"
    tmp.mkdir(parents=True, exist_ok=True)
    for s in syms:
        fetch(s, (today - timedelta(days=live["history_start_days"])).isoformat()).to_csv(tmp / f"{s}.csv")
        df = load_csv(tmp / f"{s}.csv")
        rep = validate(df, s)
        quality[s] = {"ok": rep.ok, "last": rep.last, "errors": rep.errors, "warnings": rep.warnings}
        if not rep.ok or rep.last != today.isoformat():
            print(f"DATENFEHLER {s}: {rep.errors or 'letzter Tag ' + str(rep.last) + ' != ' + today.isoformat()}")
            return 1
        frames[s] = df
    _, closes = panel(frames, syms)
    sig_date, target = strategies.current_target(closes, p, month_end)
    target = {k: round(v, 6) for k, v in target.items() if v > 0}

    acct = broker.account()
    equity, cash = float(acct["equity"]), float(acct["cash"])
    values = {s: float(v["market_value"]) for s, v in broker.positions().items()}
    orders, reason = build_orders(target, equity, values, month_end=month_end,
                                  drift_band=live["drift_band"], min_order=live["min_order_usd"])
    monthly = strategies.monthly_closes(closes.loc[:sig_date]).tail(13).round(4)
    monthly.index = monthly.index.astype(str)
    proposal = {
        "date": today.isoformat(), "mode": broker.mode, "strategy": name, "strategy_params": p,
        "month_end": month_end, "signal_date": str(sig_date.date()), "target_weights": target,
        "reason": reason, "account": {"equity": equity, "cash": cash, "positions_usd": values},
        "inputs_monthly_adj_closes": monthly.to_dict(),
        "last_close": closes.iloc[-1].round(4).to_dict(), "data_quality": quality, "orders": orders,
    }
    proposal = json.loads(json.dumps(proposal, default=str))  # Hash über exakt das, was gespeichert wird
    proposal["sha256"] = canonical_hash(proposal)
    out = ROOT / "proposals" / f"{today}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(proposal, indent=2, ensure_ascii=False, default=str))
    eq_path = ROOT / "journal/equity.csv"
    append_csv(eq_path, {"date": today.isoformat(), "equity": equity, "cash": cash,
                         "peak": peak_equity(eq_path, equity)})
    print(f"{today}: {len(orders)} Orders vorgeschlagen ({reason}). Ziel: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
