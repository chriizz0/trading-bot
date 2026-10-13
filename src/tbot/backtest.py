"""Tages-Portfolio-Backtester.

Ablauf je Monatsende T: Signal aus Schlusskursen <= T, Ausführung zum
Eröffnungskurs T+1 mit Slippage (Kauf teurer, Verkauf billiger) und
Ordergebühr. Erst Verkäufe, dann Käufe; Käufe werden auf verfügbares Cash
skaliert. Bruchstücke erlaubt (Alpaca unterstützt Fractional Shares).
Bewertung täglich zum Schlusskurs."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Result:
    equity: pd.Series
    trades: pd.DataFrame
    weights: pd.DataFrame  # Zielgewichte je Signaltag
    costs: float


def run(opens: pd.DataFrame, closes: pd.DataFrame, signal_fn, *, initial: float = 10_000.0,
        slippage_bps: float = 5.0, commission: float = 0.0, start: str | None = None,
        rebalance_dates: pd.DatetimeIndex | None = None) -> Result:
    from .strategies import month_end_dates

    idx = closes.index
    if rebalance_dates is None:
        rebalance_dates = month_end_dates(idx)
    if start is not None:
        rebalance_dates = rebalance_dates[rebalance_dates >= pd.Timestamp(start)]
    s = slippage_bps / 1e4
    pos = {c: 0.0 for c in closes.columns}
    cash = initial
    pending: tuple[pd.Timestamp, dict] | None = None
    rebal = set(rebalance_dates)
    eq, trades, wrows, total_cost = {}, [], {}, 0.0
    first = rebalance_dates[0] if len(rebalance_dates) else idx[-1]

    for i, d in enumerate(idx):
        if pending is not None:
            sig_day, target = pending
            px = opens.loc[d]
            value = cash + sum(q * px[c] for c, q in pos.items())
            want = {c: target.get(c, 0.0) * value / px[c] for c in pos}
            # Verkäufe
            for c, q in pos.items():
                diff = want[c] - q
                if diff < -1e-9:
                    fill = px[c] * (1 - s)
                    cash += -diff * fill - commission
                    total_cost += -diff * px[c] * s + commission
                    pos[c] = q + diff
                    trades.append((d, sig_day, c, diff, fill))
            # Käufe
            buys = {c: (want[c] - pos[c]) for c in pos if want[c] - pos[c] > 1e-9}
            need = sum(q * px[c] * (1 + s) for c, q in buys.items()) + commission * len(buys)
            scale = min(1.0, max(cash, 0.0) / need) if need > 0 else 1.0
            for c, q in buys.items():
                q *= scale
                fill = px[c] * (1 + s)
                cash -= q * fill + commission
                total_cost += q * px[c] * s + commission
                pos[c] += q
                trades.append((d, sig_day, c, q, fill))
            pending = None
        if d in rebal and i + 1 < len(idx):
            target = signal_fn(closes.loc[:d])  # kein Zugriff auf Daten nach T
            if target:
                tot = sum(target.values())
                target = {k: v / tot for k, v in target.items()}
                wrows[d] = target
                pending = (d, target)
        if d >= first:
            eq[d] = cash + sum(q * closes.at[d, c] for c, q in pos.items())

    trades_df = pd.DataFrame(trades, columns=["date", "signal_date", "symbol", "qty", "fill"])
    return Result(equity=pd.Series(eq, name="equity"), trades=trades_df,
                  weights=pd.DataFrame.from_dict(wrows, orient="index").fillna(0.0), costs=total_cost)
