"""EXP-301: diversifiziertes Trendfolgen (Time-Series Momentum), vektorisiert.

Konventionen (kein Look-ahead):
- Gewichte w_t werden nur aus Renditen bis einschließlich Tag t berechnet,
  am Tag t+1 gehandelt (konservativ: zum Schlusskurs t+1) und verdienen erst
  die Rendite von t+2 (shift(2)).
- Portfolio-Überrendite = Σ w·(r − rf) − Handelskosten − Finanzierungsaufschlag·Σ|w|.
- Gesamtrendite = Überrendite + rf (ungenutztes Kapital liegt in T-Bills)."""
from __future__ import annotations

import numpy as np
import pandas as pd

ANN = 252


def signals(excess: pd.DataFrame, lookbacks: list[int]) -> pd.DataFrame:
    cum = np.log1p(excess).cumsum()
    parts = [np.sign(cum - cum.shift(n)) for n in lookbacks]
    return sum(parts) / len(parts)


def weights(rets: pd.DataFrame, rf: pd.Series, p: dict, lookbacks: list[int]) -> pd.DataFrame:
    ex = rets.sub(rf, axis=0)
    sig = signals(ex, lookbacks)
    vol = ex.ewm(span=p["asset_vol_lookback_days"], min_periods=p["asset_vol_lookback_days"]).std() * np.sqrt(ANN)
    raw = sig * p["asset_target_vol"] / vol
    raw = raw.div(raw.notna().sum(axis=1).clip(lower=1), axis=0)  # gleiches Risikobudget je verfügbarem Markt
    # Portfolio auf Zielvolatilität skalieren – geschätzt mit vergangenen Renditen der Rohgewichte
    port = (raw.shift(1) * ex).sum(axis=1, min_count=1)
    pvol = port.rolling(p["portfolio_vol_lookback_days"], min_periods=p["portfolio_vol_lookback_days"]).std() * np.sqrt(ANN)
    w = raw.mul(p["portfolio_target_vol"] / pvol, axis=0)
    gross = w.abs().sum(axis=1)
    w = w.mul((p["max_gross_leverage"] / gross).clip(upper=1.0), axis=0)
    # wöchentlich: nur am letzten Handelstag der Woche neu setzen, sonst halten
    wk = w.index.to_series().dt.to_period("W")
    last = wk != wk.shift(-1)
    return w.where(last).ffill().fillna(0.0)


def run(rets: pd.DataFrame, rf: pd.Series, w: pd.DataFrame, cost_bps: float, markup_pa: float) -> pd.DataFrame:
    ex = rets.sub(rf, axis=0)
    held = w.shift(2).fillna(0.0)                       # Signal t → Handel t+1 → wirkt ab t+2
    gross_ret = (held * ex.fillna(0.0)).sum(axis=1)
    turnover = (w - w.shift(1).fillna(0.0)).abs().sum(axis=1).shift(1).fillna(0.0)  # Handelstag t+1
    trade_cost = turnover * cost_bps / 1e4
    fin = held.abs().sum(axis=1) * markup_pa / ANN
    excess = gross_ret - trade_cost - fin
    return pd.DataFrame({"excess": excess, "total": excess + rf, "gross_excess": gross_ret, "trade_cost": trade_cost,
                         "financing": fin, "turnover": turnover, "gross_leverage": held.abs().sum(axis=1)})


def stats(df: pd.DataFrame, spy_ex: pd.Series | None = None) -> dict:
    if len(df) < 20:
        return {}
    e, t = df["excess"], df["total"]
    curve = (1 + t).cumprod()
    years = len(t) / ANN
    out = {
        "start": str(df.index[0].date()), "end": str(df.index[-1].date()),
        "cagr_total": float(curve.iloc[-1] ** (1 / years) - 1),
        "vol": float(e.std() * np.sqrt(ANN)),
        "sharpe": float(e.mean() / e.std() * np.sqrt(ANN)) if e.std() > 0 else float("nan"),
        "max_drawdown": float((curve / curve.cummax() - 1).min()),
        "avg_gross_leverage": float(df["gross_leverage"].mean()),
        "turnover_pa": float(df["turnover"].sum() / years),
        "cost_pa": float((df["trade_cost"].sum() + df["financing"].sum()) / years),
    }
    if spy_ex is not None:
        out["corr_spy"] = float(e.corr(spy_ex.reindex(e.index)))
    return out
