"""Capital.com DEMO: Epics und Handelsbedingungen für US500, US100, DE40 → reports/capital-markets.json.

Schreibt keine Kontodaten. Mit --test-order: kleinste Größe (BUY) mit Stop eröffnen, nach 10 s
schließen, Ablauf nach reports/capital-test-order.json. Zugangsdaten aus .env (siehe src/tbot/capital.py).

    python scripts/capital_markets.py [--test-order [--epic US500]]
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

from common import ROOT
from tbot.capital import Capital, CapitalError, load_env, position_deal_id

SYMBOLS = ["US500", "US100", "DE40"]
REPORT = ROOT / "reports/capital-markets.json"
ORDER_LOG = ROOT / "reports/capital-test-order.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def find_epic(cap: Capital, symbol: str) -> tuple[str, list[dict]]:
    hits = cap.search_markets(symbol)
    cands = [{k: m.get(k) for k in ("epic", "instrumentName", "instrumentType")} for m in hits]
    exact = [m["epic"] for m in hits if m.get("epic") == symbol]
    idx = [m["epic"] for m in hits if m.get("instrumentType") == "INDICES"]
    if not (exact or idx):
        raise CapitalError(f"Kein Index-Epic für {symbol} gefunden: {cands}")
    return (exact or idx)[0], cands


def describe(cap: Capital, symbol: str) -> dict:
    epic, cands = find_epic(cap, symbol)
    m = cap.market(epic)
    inst, rules, snap = m.get("instrument", {}), m.get("dealingRules", {}), m.get("snapshot", {})
    bid, offer = snap.get("bid"), snap.get("offer")
    return {
        "symbol": symbol,
        "epic": epic,
        "name": inst.get("name"),
        "type": inst.get("type"),
        "currency": inst.get("currency"),
        "lot_size": inst.get("lotSize"),
        "min_deal_size": rules.get("minDealSize"),
        "max_deal_size": rules.get("maxDealSize"),
        "min_size_increment": rules.get("minSizeIncrement"),
        "min_stop_or_profit_distance": rules.get("minStopOrProfitDistance"),
        "max_stop_or_profit_distance": rules.get("maxStopOrProfitDistance"),
        "min_guaranteed_stop_distance": rules.get("minGuaranteedStopDistance"),
        "trailing_stops": rules.get("trailingStopsPreference"),
        "spread": {"bid": bid, "offer": offer,
                   "points": round(offer - bid, 6) if bid is not None and offer is not None else None,
                   "market_status": snap.get("marketStatus"), "snapshot_time": snap.get("updateTimeUTC") or snap.get("updateTime"),
                   "hinweis": "Momentaufnahme beim Abruf, schwankt mit Tageszeit"},
        "margin_factor": inst.get("marginFactor"),
        "margin_factor_unit": inst.get("marginFactorUnit"),
        "financing": inst.get("overnightFee"),
        "opening_hours": inst.get("openingHours"),
        "search_hits": cands,
    }


def test_order(cap: Capital, market: dict) -> dict:
    """Kleinste Größe BUY mit Stop, 10 s halten, schließen. Nur Demo."""
    log = {"time_utc": now(), "epic": market["epic"], "steps": []}
    step = lambda name, data: log["steps"].append({"t": now(), "step": name, **data})  # noqa: E731
    if market["spread"]["market_status"] != "TRADEABLE":
        step("abbruch", {"grund": f"Markt nicht handelbar ({market['spread']['market_status']})"})
        return log
    size = market["min_deal_size"]["value"]
    bid = market["spread"]["bid"]
    min_dist = (market["min_stop_or_profit_distance"] or {}).get("value") or 0
    unit = (market["min_stop_or_profit_distance"] or {}).get("unit")
    dist_pts = max(bid * 0.01, (bid * min_dist / 100 if unit == "PERCENTAGE" else min_dist) * 2)
    stop = round(bid - dist_pts, 1)
    opened = cap.open_position(market["epic"], "BUY", size, stop_level=stop)
    step("eröffnet", {"size": size, "stop_level": stop, "dealStatus": opened.get("dealStatus"),
                      "level": opened.get("level"), "reason": opened.get("reason"),
                      "affectedDeals": opened.get("affectedDeals")})
    if opened.get("dealStatus") != "ACCEPTED":
        return log
    deal_id = position_deal_id(opened)
    try:
        time.sleep(10)
        pos = [p for p in cap.positions() if p.get("position", {}).get("dealId") == deal_id]
        step("offen", {"gefunden": bool(pos), "stopLevel": pos[0]["position"].get("stopLevel") if pos else None})
    finally:
        closed = cap.close_position(deal_id)
        step("geschlossen", {"dealStatus": closed.get("dealStatus"), "level": closed.get("level"),
                             "reason": closed.get("reason"), "affectedDeals": closed.get("affectedDeals")})
    left = [p for p in cap.positions() if p.get("position", {}).get("dealId") == deal_id]
    step("kontrolle", {"noch_offen": bool(left)})
    return log


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--test-order", action="store_true", help="kleinste Demo-Position mit Stop öffnen/schließen")
    ap.add_argument("--epic", default="US500", choices=SYMBOLS, help="Markt für --test-order")
    args = ap.parse_args()

    cap = Capital(load_env(ROOT / ".env"))
    markets = {s: describe(cap, s) for s in SYMBOLS}
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps({"source": cap.base, "fetched_utc": now(), "markets": markets},
                                 indent=2, ensure_ascii=False) + "\n")
    for s, m in markets.items():
        print(f"{s}: epic={m['epic']} min={m['min_deal_size']} spread={m['spread']['points']} "
              f"margin={m['margin_factor']}{m['margin_factor_unit'] or ''} status={m['spread']['market_status']}")
    print(f"→ {REPORT.relative_to(ROOT)}")

    if args.test_order:
        log = test_order(cap, markets[args.epic])
        ORDER_LOG.write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n")
        for s in log["steps"]:
            print(f"{s['t']} {s['step']}: {s.get('dealStatus') or s.get('grund') or ''}")
        print(f"→ {ORDER_LOG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CapitalError as e:
        raise SystemExit(f"Fehler: {e}")
