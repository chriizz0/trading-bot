"""Vorregistrierte Strategien. Jede Funktion bekommt NUR Schlusskurse bis
einschließlich Signaltag T (Monatsletzter) und liefert Zielgewichte (Summe 1)."""
from __future__ import annotations

import pandas as pd


def month_end_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Letzter Handelstag jedes Monats. Der letzte Index-Tag zählt nur, wenn
    der Monat danach erkennbar endet – im Backtest also nie der laufende Monat."""
    s = index.to_series()
    nxt = s.shift(-1)
    mask = nxt.notna() & (nxt.dt.to_period("M") != s.dt.to_period("M"))
    return pd.DatetimeIndex(s[mask].values)


def monthly_closes(closes: pd.DataFrame) -> pd.DataFrame:
    return closes.groupby(closes.index.to_period("M")).last()


def sma_trend(closes: pd.DataFrame, p: dict) -> dict[str, float]:
    m = monthly_closes(closes)
    n = p["sma_months"]
    if len(m) < n:
        return {}
    w = {}
    each = 1.0 / len(p["assets"])
    for a in p["assets"]:
        sma = m[a].iloc[-n:].mean()
        key = a if m[a].iloc[-1] > sma else p["cash"]
        w[key] = w.get(key, 0.0) + each
    return w


def dual_momentum(closes: pd.DataFrame, p: dict) -> dict[str, float]:
    m = monthly_closes(closes)
    n = p["lookback_months"]
    if len(m) < n + 1:
        return {}
    ret = m.iloc[-1] / m.iloc[-1 - n] - 1
    if ret["SPY"] > ret[p["cash"]]:
        best = max(p["equities"], key=lambda s: ret[s])
        return {best: 1.0}
    return {p["bonds"]: 1.0}


def constant(_closes: pd.DataFrame, weights: dict) -> dict[str, float]:
    return dict(weights)


REGISTRY = {"sma_trend": sma_trend, "dual_momentum": dual_momentum,
            "constant": lambda _c, p: dict(p["weights"])}


def symbols_of(p: dict) -> list[str]:
    syms = list(p.get("assets", [])) + list(p.get("equities", [])) + list(p.get("weights", {}))
    for k in ("bonds", "cash"):
        if k in p:
            syms.append(p[k])
    if p.get("type") == "dual_momentum" and "SPY" not in syms:
        syms.append("SPY")
    return sorted(set(syms))


def signal(closes_until_t: pd.DataFrame, p: dict) -> dict[str, float]:
    return REGISTRY[p["type"]](closes_until_t, p)


def current_target(closes: pd.DataFrame, p: dict, today_is_month_end: bool) -> tuple[pd.Timestamp, dict[str, float]]:
    """Ziel laut letztem abgeschlossenen Monatsende (live). Ist heute Monatsletzter, gilt heute."""
    if today_is_month_end:
        t = closes.index[-1]
    else:
        ends = month_end_dates(closes.index)
        t = ends[-1]
    return t, signal(closes.loc[:t], p)
