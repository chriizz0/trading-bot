"""Reine Logik für Vorschlag, Review-Prüfung und Risikofilter (ohne Netzwerk, testbar)."""
from __future__ import annotations

import hashlib
import json

VALID_DECISIONS = {"approve", "veto"}
VETO_REASONS = {"data_error", "rule_mismatch", "risk_breach", "corporate_action", "market_disruption", "other"}


def canonical_hash(obj: dict) -> str:
    body = {k: v for k, v in obj.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def build_orders(target: dict[str, float], equity: float, values: dict[str, float], *, month_end: bool,
                 drift_band: float, min_order: float) -> tuple[list[dict], str]:
    """Orders (Notional in USD), um von aktuellen Positionswerten zum Ziel zu kommen."""
    syms = sorted(set(target) | {s for s, v in values.items() if abs(v) > 0})
    actual_w = {s: values.get(s, 0.0) / equity for s in syms}
    max_dev = max((abs(actual_w[s] - target.get(s, 0.0)) for s in syms), default=0.0)
    if not month_end and max_dev <= drift_band:
        return [], f"kein Monatsende, max. Abweichung {max_dev:.1%} <= Band {drift_band:.0%}"
    reason = "Monatsende-Rebalancing" if month_end else f"Abweichung {max_dev:.1%} > Band (Ziel noch nicht umgesetzt)"
    orders = []
    for s in syms:
        diff = target.get(s, 0.0) * equity - values.get(s, 0.0)
        if abs(diff) < min_order:
            continue
        close_all = target.get(s, 0.0) == 0.0 and values.get(s, 0.0) > 0
        orders.append({"id": f"{s}-{'sell' if diff < 0 else 'buy'}", "symbol": s, "side": "sell" if diff < 0 else "buy",
                       "notional": round(abs(diff), 2), "close_position": close_all,
                       "weight_from": round(actual_w[s], 4), "weight_to": round(target.get(s, 0.0), 4)})
    orders.sort(key=lambda o: o["side"] != "sell")  # Verkäufe zuerst
    return orders, reason


def approved_orders(proposal: dict, review: dict | None) -> tuple[list[dict], list[str]]:
    """Nur ausdrücklich freigegebene Orders eines unveränderten Vorschlags. Fehlt das Review → nichts."""
    msgs = []
    if review is None:
        return [], ["kein Review vorhanden – keine Ausführung"]
    if canonical_hash(proposal) != proposal.get("sha256"):
        return [], ["Vorschlag wurde nach Erstellung verändert – keine Ausführung"]
    if review.get("proposal_sha256") != proposal["sha256"]:
        return [], ["Review gehört nicht zu diesem Vorschlag – keine Ausführung"]
    decisions = {d.get("order_id"): d for d in review.get("decisions", [])}
    out = []
    for o in proposal["orders"]:
        d = decisions.get(o["id"])
        if d is None or d.get("decision") not in VALID_DECISIONS:
            msgs.append(f"{o['id']}: keine gültige Entscheidung → nicht ausgeführt")
        elif d["decision"] == "veto":
            msgs.append(f"{o['id']}: Veto ({d.get('reason_code')}): {d.get('reason', '')}")
        else:
            out.append(o)
    return out, msgs


def risk_filter(orders: list[dict], *, universe: list[str], equity: float, peak_equity: float, cash: float,
                max_drawdown: float, mode: str, live_max_equity: float | None) -> tuple[list[dict], list[str], bool]:
    """Harte Regeln, die auch ein freigegebener Vorschlag nicht umgehen kann. Rückgabe: Orders, Meldungen, halt."""
    msgs, halt = [], False
    dd = equity / peak_equity - 1 if peak_equity > 0 else 0.0
    if dd < -max_drawdown:
        halt = True
        msgs.append(f"KILL-SWITCH: Drawdown {dd:.1%} < -{max_drawdown:.0%} – keine Käufe, manuelle Freigabe nötig")
    if mode == "live" and live_max_equity is not None and equity > live_max_equity * 1.25:
        halt = True
        msgs.append(f"Live-Kapital {equity:.0f} über Obergrenze {live_max_equity:.0f} – keine Käufe")
    out = []
    budget = cash + sum(o["notional"] for o in orders if o["side"] == "sell")
    for o in orders:
        if o["symbol"] not in universe:
            msgs.append(f"{o['id']}: Symbol nicht im Universum – verworfen")
            continue
        if o["side"] == "buy":
            if halt:
                msgs.append(f"{o['id']}: Kauf wegen Halt verworfen")
                continue
            if o["notional"] > budget:
                o = {**o, "notional": round(max(budget, 0.0) * 0.995, 2)}
                msgs.append(f"{o['id']}: auf verfügbares Budget gekürzt")
            if o["notional"] <= 1:
                continue
            budget -= o["notional"]
        out.append(o)
    return out, msgs, halt
