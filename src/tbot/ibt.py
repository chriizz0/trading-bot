"""Intraday-/Swing-Backtester für CFDs auf Kerzenbasis.

Regeln (konservativ):
- Einstieg zum Open der Signal-Folgekerze, Kauf zum Ask (Mid + halber Spread) + Slippage.
- Stop wird vor jedem anderen Ausstieg in derselben Kerze geprüft; Gap über den Stop
  → Ausführung zum (schlechteren) Open. Stop-Fills mit Extra-Slippage.
- Zeit-Ausstieg zum Close der angegebenen Kerze, Signal-Ausstieg zum Open der Folgekerze.
- Übernachtfinanzierung je 23:00-Berlin-Überschreitung, freitags dreifach.
- Positionsgröße: Risiko % des Kapitals / Stopabstand, gedeckelt durch Max-Hebel.
- Höchstens eine Position je Instrument; Signale während offener Position verfallen."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from .intraday import in_session_mask


@dataclass
class Signal:
    i: int                      # Kerze, zu deren Open eingestiegen wird
    direction: int              # +1 long, -1 short
    stop: float                 # Stopkurs (Mid)
    exit_at: int | None = None  # Zeit-Ausstieg zum Close dieser Kerze
    exit_fn: Callable[[int], bool] | None = None  # True bei Close von j → Ausstieg Open j+1


def _nights(t0: pd.Timestamp, t1: pd.Timestamp, cutoff: str, tz: str) -> int:
    a, b = t0.tz_convert(tz), t1.tz_convert(tz)
    hh, mm = int(cutoff[:2]), int(cutoff[3:])
    n = 0
    d = a.normalize()
    while d <= b:
        c = d + pd.Timedelta(hours=hh, minutes=mm)
        if a < c <= b and c.dayofweek < 5:  # Sa/So in Freitag x3 enthalten
            n += 3 if c.dayofweek == 4 else 1
        d += pd.Timedelta(days=1)
    return n


def simulate(bars: pd.DataFrame, signals: list[Signal], inst: dict, costs: dict, risk: dict,
             bar_minutes: int = 30) -> pd.DataFrame:
    o, h, l, c = (bars[k].to_numpy() for k in ("open", "high", "low", "close"))
    idx = bars.index
    half = np.where(in_session_mask(idx, inst), inst["spread_session"], inst["spread_off"]) / 2.0
    slip, slip_stop = costs["slippage_points_market"], costs["slippage_points_stop_extra"]
    eq = float(risk["initial_equity"])
    busy_until, rows = -1, []
    for s in sorted(signals, key=lambda x: x.i):
        if s.i <= busy_until or s.i >= len(o):
            continue
        d = s.direction
        if (d > 0 and o[s.i] <= s.stop) or (d < 0 and o[s.i] >= s.stop):
            continue  # Stop bereits beim Einstieg verletzt
        entry = o[s.i] + d * (half[s.i] + slip)
        dist = abs(entry - s.stop)
        units = min(risk["risk_per_trade"] * eq / dist, risk["max_leverage"] * eq / entry)
        j, exit_px, reason, t_exit = s.i, None, None, None
        last = s.exit_at if s.exit_at is not None else len(o) - 1
        while j <= last:
            hit = (l[j] <= s.stop) if d > 0 else (h[j] >= s.stop)
            if hit:
                raw = min(o[j], s.stop) if d > 0 else max(o[j], s.stop)
                if j == s.i:
                    raw = s.stop
                exit_px, reason, t_exit = raw - d * (half[j] + slip + slip_stop), "stop", idx[j]
                break
            if s.exit_at is not None and j == s.exit_at:
                exit_px, reason, t_exit = c[j] - d * (half[j] + slip), "time", idx[j] + pd.Timedelta(minutes=bar_minutes)
                break
            if s.exit_fn is not None and j + 1 < len(o) and s.exit_fn(j):
                exit_px, reason, t_exit = o[j + 1] - d * (half[j + 1] + slip), "signal", idx[j + 1]
                j += 1
                break
            j += 1
        if exit_px is None:
            break  # Datenende mit offener Position: Trade nicht werten
        nights = _nights(idx[s.i], t_exit, costs["financing_cutoff_local"], costs["financing_cutoff_tz"])
        rate = costs["financing_long_pa"] if d > 0 else costs["financing_short_pa"]
        fin = units * entry * rate * nights / costs["financing_day_count"]
        mid_exit = exit_px + d * (half[min(j, len(o) - 1)] + slip + (slip_stop if reason == "stop" else 0))
        gross = units * d * (mid_exit - o[s.i])
        pnl = units * d * (exit_px - entry) - fin
        rows.append({"entry_time": idx[s.i], "exit_time": t_exit, "dir": d, "entry": entry, "exit": exit_px,
                     "units": units, "notional": units * entry, "leverage": units * entry / eq, "nights": nights,
                     "financing": fin, "gross_mid": gross, "costs": gross - pnl, "pnl": pnl, "ret": pnl / eq,
                     "equity_before": eq, "reason": reason})
        eq += pnl
        busy_until = j
        if eq <= 0:
            break
    return pd.DataFrame(rows)


def stats(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"trades": 0}
    r = trades["ret"]
    wins, losses = trades.loc[trades.pnl > 0, "pnl"].sum(), -trades.loc[trades.pnl < 0, "pnl"].sum()
    curve = (1 + r).cumprod()
    dd = (curve / curve.cummax().clip(lower=1.0) - 1).min()
    hold = (trades["exit_time"] - trades["entry_time"]).dt.total_seconds() / 3600
    return {
        "trades": int(len(r)), "mean_ret": float(r.mean()),
        "t_stat": float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 2 and r.std() > 0 else float("nan"),
        "profit_factor": float(wins / losses) if losses > 0 else float("inf"),
        "win_rate": float((trades.pnl > 0).mean()), "total_return": float(curve.iloc[-1] - 1),
        "max_drawdown": float(dd), "avg_hold_h": float(hold.mean()),
        "cost_share_of_gross_abs": float(trades["costs"].sum() / max(trades["gross_mid"].abs().sum(), 1e-9)),
        "avg_leverage": float(trades["leverage"].mean()),
    }
