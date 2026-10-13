"""Intraday-Daten (Dukascopy Bid/Ask, 30 Min) laden, prüfen und in Sitzungen gliedern."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OHLC = ["open", "high", "low", "close"]


def _read(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    ts = df["timestamp"]
    if np.issubdtype(ts.dtype, np.number):
        mag = float(np.nanmedian(ts))
        unit = "s" if mag < 1e11 else "ms" if mag < 1e14 else "us"
        idx = pd.to_datetime(ts, unit=unit, utc=True)
    else:
        idx = pd.to_datetime(ts, utc=True)
    return df.set_index(idx)[OHLC].astype(float).sort_index()


def load_mid(data_dir: str | Path, name: str) -> tuple[pd.DataFrame, list[str]]:
    """Mid-Kerzen aus Bid- und Ask-Datei. Rückgabe: Kerzen (UTC) und Fehlerliste."""
    d = Path(data_dir)
    bid, ask = _read(d / f"{name}-bid.csv"), _read(d / f"{name}-ask.csv")
    errors = []
    for label, x in (("bid", bid), ("ask", ask)):
        if x.index.has_duplicates:
            errors.append(f"{label}: {int(x.index.duplicated().sum())} doppelte Zeitstempel")
        if not np.isfinite(x.to_numpy()).all() or (x.to_numpy() <= 0).any():
            errors.append(f"{label}: nicht-endliche oder nicht-positive Preise")
        if (x["high"] < x[["open", "close", "low"]].max(axis=1) - 1e-9).any() or (x["low"] > x[["open", "close"]].min(axis=1) + 1e-9).any():
            errors.append(f"{label}: OHLC-Inkonsistenz")
    idx = bid.index.intersection(ask.index)
    if len(idx) < 0.99 * max(len(bid), len(ask)):
        errors.append("Bid/Ask-Zeitstempel weichen > 1 % ab")
    b, a = bid.loc[idx], ask.loc[idx]
    if (a["close"] < b["close"] - 1e-9).mean() > 0.001:
        errors.append("Ask < Bid in > 0,1 % der Kerzen")
    mid = (b + a) / 2
    # Bars ohne Preisbewegung und mit Bid==Ask-Artefakten sind bei Dukascopy oft Füllkerzen außerhalb der Handelszeit
    flat = (b["high"] == b["low"]) & (a["high"] == a["low"]) & (b["open"] == b["close"])
    mid = mid[~flat]
    return mid, errors


def session_info(bars: pd.DataFrame, inst: dict, min_cov: float) -> pd.DataFrame:
    """Je lokalem Handelstag: Sitzungs-OHLC, Positionen der ersten/letzten Sitzungskerze,
    der ersten Kerze nach Sitzungsende und die Abdeckung erwarteter 30-Min-Slots."""
    tz = inst["tz"]
    local = bars.index.tz_convert(tz)
    s0, s1 = [pd.Timedelta(hours=int(t[:2]), minutes=int(t[3:])) for t in inst["session"]]
    expected = int((s1 - s0) / pd.Timedelta(minutes=30))
    tod = local - local.normalize()
    day = local.normalize().tz_localize(None)
    pos = np.arange(len(bars))
    in_sess = (tod >= s0) & (tod < s1)
    rows = []
    df = pd.DataFrame({"day": day, "pos": pos, "in": in_sess, "tod": tod})
    for d, g in df.groupby("day", sort=True):
        sess = g[g["in"]]
        if sess.empty:
            continue
        after = g[g["tod"] >= s1]
        sp = sess["pos"].to_numpy()
        sb = bars.iloc[sp]
        rows.append({"day": d, "first": int(sp[0]), "last": int(sp[-1]),
                     "after": int(after["pos"].iloc[0]) if len(after) else -1,
                     "first_is_open": bool(sess["tod"].iloc[0] == s0),
                     "last_is_final": bool(sess["tod"].iloc[-1] == s1 - pd.Timedelta(minutes=30)),
                     "open": sb["open"].iloc[0], "high": sb["high"].max(), "low": sb["low"].min(),
                     "close": sb["close"].iloc[-1], "coverage": len(sp) / expected})
    info = pd.DataFrame(rows).set_index("day")
    info["good"] = (info["coverage"] >= min_cov) & info["first_is_open"] & info["last_is_final"]
    return info


def in_session_mask(index: pd.DatetimeIndex, inst: dict) -> np.ndarray:
    local = index.tz_convert(inst["tz"])
    tod = local - local.normalize()
    s0, s1 = [pd.Timedelta(hours=int(t[:2]), minutes=int(t[3:])) for t in inst["session"]]
    return np.asarray((tod >= s0) & (tod < s1) & (local.dayofweek < 5))


def to_hourly(bars: pd.DataFrame) -> pd.DataFrame:
    h = bars.resample("1h", label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    return h.dropna()
