"""EXP-201-Strategien. Jede Regel nutzt nur Kerzen, die zum Entscheidungszeitpunkt abgeschlossen sind."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .ibt import Signal


def imom(bars: pd.DataFrame, info: pd.DataFrame, p: dict) -> list[Signal]:
    """Entscheidung am Close der ersten Sitzungskerze (bekannt), Einstieg zum Open der letzten."""
    sigs, o, c = [], bars["open"].to_numpy(), bars["close"].to_numpy()
    days = info.index
    for k in range(1, len(days)):
        today, prev = info.iloc[k], info.iloc[k - 1]
        if not (today.good and prev.good):
            continue
        r1 = c[today["first"]] / prev["close"] - 1
        if abs(r1) <= p["min_abs_first_return"] or today["last"] <= today["first"]:
            continue
        d = 1 if r1 > 0 else -1
        i = int(today["last"])
        sigs.append(Signal(i=i, direction=d, stop=o[i] * (1 - d * p["stop_pct"]), exit_at=i))
    return sigs


def ibs(bars: pd.DataFrame, info: pd.DataFrame, p: dict) -> list[Signal]:
    """Entscheidung nach Sitzungsschluss (Sitzungs-OHLC bekannt), Einstieg zum Open der ersten Kerze danach,
    Ausstieg zum Close der letzten Sitzungskerze des nächsten Handelstags."""
    sigs, o = [], bars["open"].to_numpy()
    rng = (info["high"] - info["low"])
    atr = rng.rolling(p["atr_days"]).mean()  # nur Tage bis einschließlich heute
    for k in range(len(info) - 1):
        t, nxt = info.iloc[k], info.iloc[k + 1]
        if not (t.good and nxt.good) or t["after"] < 0 or np.isnan(atr.iloc[k]) or t["high"] <= t["low"]:
            continue
        v = (t["close"] - t["low"]) / (t["high"] - t["low"])
        if v >= p["ibs_threshold"]:
            continue
        i = int(t["after"])
        if i >= nxt["last"]:
            continue
        sigs.append(Signal(i=i, direction=1, stop=o[i] - p["stop_atr_mult"] * atr.iloc[k], exit_at=int(nxt["last"])))
    return sigs


def donch(hourly: pd.DataFrame, good_days: set, tz: str, p: dict) -> list[Signal]:
    h, l, c, o = (hourly[k].to_numpy() for k in ("high", "low", "close", "open"))
    prev_c = np.r_[c[0], c[:-1]]
    tr = np.maximum(h, prev_c) - np.minimum(l, prev_c)
    atr = pd.Series(tr).rolling(p["atr_bars"]).mean().to_numpy()
    hi_in = pd.Series(h).rolling(p["entry_bars"]).max().shift(1).to_numpy()   # Bars t-55..t-1
    lo_in = pd.Series(l).rolling(p["entry_bars"]).min().shift(1).to_numpy()
    hi_out = pd.Series(h).rolling(p["exit_bars"]).max().shift(1).to_numpy()
    lo_out = pd.Series(l).rolling(p["exit_bars"]).min().shift(1).to_numpy()
    local_day = hourly.index.tz_convert(tz).normalize().tz_localize(None)
    sigs = []
    for t in range(len(c) - 1):
        if np.isnan(hi_in[t]) or np.isnan(atr[t]) or local_day[t + 1] not in good_days:
            continue
        d = 1 if c[t] > hi_in[t] else -1 if c[t] < lo_in[t] else 0
        if d == 0:
            continue
        i = t + 1
        stop = o[i] - d * p["stop_atr_mult"] * atr[t]
        fn = (lambda j: c[j] < lo_out[j]) if d > 0 else (lambda j: c[j] > hi_out[j])
        sigs.append(Signal(i=i, direction=d, stop=stop, exit_fn=fn))
    return sigs
