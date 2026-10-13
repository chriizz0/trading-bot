"""Während der US-Handelszeit: nur von Claude freigegebene Orders des letzten
Vorschlags ausführen – nach harten Risikoregeln. --dry-run sendet nichts."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from common import ROOT, append_csv, load_cfg, market_today, peak_equity, strategy_params, trading_days

from tbot import strategies
from tbot.broker import Alpaca
from tbot.live import approved_orders, risk_filter


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    research, live = load_cfg()
    if not live["strategy"]:
        print("Keine freigegebene Strategie – nichts zu tun.")
        return 0
    broker = Alpaca()
    if not broker.clock()["is_open"]:
        print("Markt geschlossen – keine Ausführung.")
        return 0
    today = market_today(broker)
    prev = [d for d in trading_days(broker, today - timedelta(days=10), today) if d < today][-1].isoformat()
    pfile = ROOT / "proposals" / f"{prev}.json"
    done = ROOT / "journal/executions" / f"{prev}.json"
    if not pfile.exists():
        print(f"Kein Vorschlag vom letzten Handelstag {prev}.")
        return 0
    if done.exists():
        print(f"Vorschlag {prev} wurde bereits verarbeitet.")
        return 0
    proposal = json.loads(pfile.read_text())
    rfile = ROOT / "reviews" / f"{prev}.json"
    review = json.loads(rfile.read_text()) if rfile.exists() else None
    if not proposal["orders"]:
        print("Vorschlag enthält keine Orders.")
        return 0
    orders, msgs = approved_orders(proposal, review)

    acct = broker.account()
    equity, cash = float(acct["equity"]), float(acct["cash"])
    halt_file = ROOT / "journal/HALT"
    universe = strategies.symbols_of(strategy_params(research, live["strategy"]))
    orders, rmsgs, halt = risk_filter(orders, universe=universe, equity=equity,
                                      peak_equity=peak_equity(ROOT / "journal/equity.csv", equity), cash=cash,
                                      max_drawdown=live["max_drawdown_halt"], mode=broker.mode,
                                      live_max_equity=live["live_max_equity_usd"])
    msgs += rmsgs
    if halt_file.exists():
        halt = True
        orders = [o for o in orders if o["side"] == "sell"]
        msgs.append("HALT-Datei vorhanden – nur Verkäufe")
    results = []
    if a.dry_run:
        print(json.dumps({"orders": orders, "messages": msgs}, indent=2, ensure_ascii=False))
        return 0
    positions = broker.positions()
    for o in [o for o in orders if o["side"] == "sell"]:
        held = float(positions.get(o["symbol"], {}).get("market_value", 0))
        if o["close_position"] or o["notional"] >= 0.98 * held:
            r = broker.close_position(o["symbol"])
        else:
            r = broker.market_order(o["symbol"], "sell", o["notional"], f"{prev}-{o['id']}")
        results.append((o, r))
    filled = broker.wait_filled([r["id"] for _, r in results]) if results else {}
    cash_now = float(broker.account()["cash"])  # Cash, nicht Buying Power: kein Hebel
    for o in [o for o in orders if o["side"] == "buy"]:
        n = min(o["notional"], cash_now * 0.995)
        if n < 1:
            msgs.append(f"{o['id']}: kein Cash mehr")
            continue
        r = broker.market_order(o["symbol"], "buy", n, f"{prev}-{o['id']}")
        cash_now -= n
        results.append(({**o, "notional": round(n, 2)}, r))
    filled.update(broker.wait_filled([r["id"] for _, r in results if r["id"] not in filled]) if results else {})
    now = datetime.now(timezone.utc).isoformat()
    log = []
    for o, r in results:
        f = filled.get(r["id"], r)
        row = {"ts": now, "proposal": prev, "symbol": o["symbol"], "side": o["side"], "notional_planned": o["notional"],
               "status": f.get("status"), "filled_qty": f.get("filled_qty"), "filled_avg_price": f.get("filled_avg_price"),
               "order_id": r["id"], "mode": broker.mode}
        append_csv(ROOT / "journal/orders.csv", row)
        log.append(row)
    if halt:
        halt_file.write_text(f"{now}\n" + "\n".join(msgs) + "\n")
    done.parent.mkdir(parents=True, exist_ok=True)
    done.write_text(json.dumps({"proposal": str(prev), "proposal_sha256": proposal["sha256"], "executed_at": now,
                                "messages": msgs, "orders": log, "halt": halt}, indent=2, ensure_ascii=False))
    print("\n".join(msgs) or "ok", f"\n{len(log)} Orders gesendet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
