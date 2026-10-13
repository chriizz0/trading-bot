"""Tagesdaten laden und prüfen. Geprüfte Regeln übernommen aus dem Altprojekt
(trading-research, DQG-1): endliche Werte, positive Preise, OHLC-Konsistenz,
eindeutige aufsteigende Zeitstempel, Lücken, Ausreißer."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ["open", "high", "low", "close", "adj_close", "volume"]


@dataclass
class QualityReport:
    symbol: str
    rows: int = 0
    first: str | None = None
    last: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(df: pd.DataFrame, symbol: str, ohlc_tolerance: float = 0.005) -> QualityReport:
    rep = QualityReport(symbol=symbol, rows=len(df))
    if df.empty:
        rep.errors.append("keine Daten")
        return rep
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        rep.errors.append(f"fehlende Spalten: {missing}")
        return rep
    rep.first, rep.last = str(df.index[0].date()), str(df.index[-1].date())
    if not df.index.is_monotonic_increasing:
        rep.errors.append("Datumsindex nicht aufsteigend")
    if df.index.has_duplicates:
        rep.errors.append(f"{int(df.index.duplicated().sum())} doppelte Daten")
    prices = df[["open", "high", "low", "close", "adj_close"]]
    values = prices.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        rep.errors.append(f"{int((~np.isfinite(values)).sum())} nicht-endliche Preise")
    if (values <= 0).any():
        rep.errors.append("Preise <= 0")
    vol = df["volume"].to_numpy(dtype=float)
    if not np.isfinite(vol).all() or (vol < 0).any():
        rep.errors.append("ungültiges Volumen")
    if rep.errors:
        return rep
    hi = df["high"] * (1 + ohlc_tolerance)
    lo = df["low"] * (1 - ohlc_tolerance)
    bad = (df[["open", "close"]].max(axis=1) > hi) | (df[["open", "close"]].min(axis=1) < lo) | (df["high"] < df["low"])
    if bad.any():
        rep.errors.append(f"{int(bad.sum())} OHLC-Inkonsistenzen (z. B. {df.index[bad][0].date()})")
    factor = df["adj_close"] / df["close"]
    if (factor > 1.5).any() or (factor < 0.05).any():
        rep.errors.append("unplausibler Adjustierungsfaktor")
    gaps = df.index.to_series().diff().dt.days
    if (gaps > 7).any():
        rep.warnings.append(f"{int((gaps > 7).sum())} Lücken > 7 Kalendertage")
    ret = df["adj_close"].pct_change().abs()
    if (ret > 0.25).any():
        rep.warnings.append(f"{int((ret > 0.25).sum())} Tagesbewegungen > 25 % (prüfen: Split?)")
    return rep


def load_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    return df[COLUMNS].astype(float)


def adjusted(df: pd.DataFrame) -> pd.DataFrame:
    """Gesamtrendite-adjustierte Open/Close (Dividenden + Splits)."""
    f = df["adj_close"] / df["close"]
    return pd.DataFrame({"open": df["open"] * f, "close": df["adj_close"]}, index=df.index)


def load_universe(data_dir: str | Path, symbols: list[str]) -> tuple[dict[str, pd.DataFrame], list[QualityReport]]:
    frames, reports = {}, []
    for sym in symbols:
        p = Path(data_dir) / f"{sym}.csv"
        if not p.exists():
            reports.append(QualityReport(symbol=sym, errors=["Datei fehlt"]))
            continue
        df = load_csv(p)
        rep = validate(df, sym)
        reports.append(rep)
        if rep.ok:
            frames[sym] = df
    return frames, reports


def panel(frames: dict[str, pd.DataFrame], symbols: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Adjustierte Open- und Close-Matrizen auf gemeinsamem Kalender (nur Tage, an denen alle Symbole Daten haben)."""
    adj = {s: adjusted(frames[s]) for s in symbols}
    opens = pd.concat({s: a["open"] for s, a in adj.items()}, axis=1).dropna()
    closes = pd.concat({s: a["close"] for s, a in adj.items()}, axis=1).dropna()
    idx = opens.index.intersection(closes.index)
    return opens.loc[idx], closes.loc[idx]


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

