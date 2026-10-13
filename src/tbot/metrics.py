from __future__ import annotations

import math

import pandas as pd


def summarize(equity: pd.Series, trades: pd.DataFrame | None = None) -> dict:
    equity = equity.dropna()
    if len(equity) < 2:
        return {}
    r = equity.pct_change().dropna()
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else float("nan")
    vol = r.std() * math.sqrt(252)
    sharpe = (r.mean() * 252) / vol if vol > 0 else float("nan")
    down = r[r < 0].std() * math.sqrt(252)
    sortino = (r.mean() * 252) / down if down > 0 else float("nan")
    dd = equity / equity.cummax() - 1
    maxdd = dd.min()
    monthly = equity.resample("ME").last().pct_change().dropna()
    out = {
        "start": str(equity.index[0].date()), "end": str(equity.index[-1].date()),
        "years": round(years, 2), "cagr": cagr, "vol": vol, "sharpe": sharpe, "sortino": sortino,
        "max_drawdown": maxdd, "calmar": cagr / abs(maxdd) if maxdd < 0 else float("nan"),
        "worst_month": monthly.min() if len(monthly) else float("nan"),
        "total_return": equity.iloc[-1] / equity.iloc[0] - 1,
    }
    if trades is not None:
        t = trades[(trades["date"] >= equity.index[0]) & (trades["date"] <= equity.index[-1])]
        out["orders"] = int(len(t))
        out["rebalances_with_trades"] = int(t["signal_date"].nunique()) if len(t) else 0
    return out


def slice_equity(equity: pd.Series, start: str | None, end: str | None) -> pd.Series:
    e = equity
    if start:
        e = e[e.index >= pd.Timestamp(start)]
    if end:
        e = e[e.index <= pd.Timestamp(end)]
    return e
