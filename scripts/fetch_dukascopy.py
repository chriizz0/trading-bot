"""Dukascopy-Minutenkerzen (bi5) direkt laden und zu 30-Min-Kerzen (UTC) bündeln.

dukascopy-node nutzt eine neue JSON-Schnittstelle, die Server-IPs mit HTTP 202
abweist. Der klassische bi5-Datenfeed funktioniert mit Browser-User-Agent.
Format je Datensatz (24 Byte, big endian): Sekunden seit Tagesbeginn (UTC),
Open, Close, Low, High (ganzzahlig, / DIVISOR), Volumen (float)."""
from __future__ import annotations

import argparse
import lzma
import struct
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

SYMBOLS = {"US500": "USA500IDXUSD", "US100": "USATECHIDXUSD", "DE40": "DEUIDXEUR"}
DIVISOR = 1000.0  # Dukascopy-Indizes: 3 Nachkommastellen
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
REC = struct.Struct(">5if")


def url(sym: str, d: date, side: str) -> str:
    return f"https://datafeed.dukascopy.com/datafeed/{sym}/{d.year}/{d.month - 1:02d}/{d.day:02d}/{side.upper()}_candles_min_1.bi5"


def parse_bi5(raw: bytes, d: date) -> list[tuple]:
    if not raw:
        return []
    base = pd.Timestamp(d, tz="UTC").value // 10**6
    return [(base + t * 1000, o / DIVISOR, h / DIVISOR, l / DIVISOR, c / DIVISOR)
            for t, o, c, l, h, _v in REC.iter_unpack(lzma.decompress(raw))]


def fetch_day(sym: str, d: date, side: str, retries: int = 8) -> list[tuple] | None:
    req = urllib.request.Request(url(sym, d, side), headers={"User-Agent": UA, "Referer": "https://www.dukascopy.com/"})
    for k in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                status = r.status
            if status == 200:
                return parse_bi5(raw, d)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []
        except (urllib.error.URLError, TimeoutError, lzma.LZMAError, ConnectionError):
            pass
        time.sleep(min(3 * 2 ** k, 60))
    return None  # endgültig fehlgeschlagen → als fehlender Tag protokolliert


def to_m30(rows: list[tuple]) -> pd.DataFrame:
    m1 = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    m1.index = pd.to_datetime(m1["timestamp"], unit="ms", utc=True)
    m30 = m1.resample("30min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    m30.insert(0, "timestamp", m30.index.as_unit("ms").asi8)
    return m30


def fetch_month(name: str, side: str, y: int, m: int, cache: Path, workers: int, pause: float) -> tuple[int | None, list[str]]:
    """Einen Monat laden und als 30-Min-CSV im Cache ablegen (fortsetzbar)."""
    f = cache / f"{name}-{side}-{y}-{m:02d}.csv"
    if f.exists():
        return -1, []
    d0 = date(y, m, 1)
    d1 = min((date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)), date.today() - timedelta(days=1))
    days = [d0 + timedelta(n) for n in range((d1 - d0).days + 1) if (d0 + timedelta(n)).weekday() != 5]

    def get(d):
        time.sleep(pause)
        return fetch_day(SYMBOLS[name], d, side)

    with ThreadPoolExecutor(workers) as ex:
        parts = list(ex.map(get, days))
    missing = [str(d) for d, p in zip(days, parts) if p is None]
    if len(missing) > 2:  # Monat nicht cachen → beim nächsten Lauf erneut versuchen
        return None, missing
    rows = [r for p in parts if p for r in p]
    df = to_m30(rows) if rows else pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    df.to_csv(f, index=False, float_format="%.3f")
    return len(df), missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", nargs="+", default=list(SYMBOLS))
    ap.add_argument("--from", dest="start", default="2016-01-01")
    ap.add_argument("--out", default="data/intraday")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--pause", type=float, default=0.15, help="Pause je Anfrage und Thread (Sekunden)")
    a = ap.parse_args()
    out, cache = Path(a.out), Path(a.out) / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    s0, end = date.fromisoformat(a.start), date.today() - timedelta(days=1)
    months = [(y, m) for y in range(s0.year, end.year + 1) for m in range(1, 13)
              if date(y, m, 1) >= date(s0.year, s0.month, 1) and date(y, m, 1) <= end]
    failed = []
    for name in a.names:
        for side in ("bid", "ask"):
            for y, m in months:
                t0 = time.time()
                n, missing = fetch_month(name, side, y, m, cache, a.workers, a.pause)
                if n == -1:
                    continue
                status = "OK" if n is not None else "UNVOLLSTÄNDIG – später erneut"
                print(f"{name} {side} {y}-{m:02d}: {n} Kerzen, {len(missing)} Tage fehlgeschlagen, "
                      f"{time.time() - t0:.0f}s {status}", flush=True)
                if n is None:
                    failed.append(f"{name}-{side}-{y}-{m:02d}")
            files = sorted(cache.glob(f"{name}-{side}-*.csv"))
            frames = [pd.read_csv(f) for f in files if f.stat().st_size > 40]
            if frames:
                df = pd.concat(frames).drop_duplicates("timestamp").sort_values("timestamp")
                df.to_csv(out / f"{name}-{side}.csv", index=False)
                print(f"== {name} {side}: {len(df)} Kerzen aus {len(files)} Monaten → {out / f'{name}-{side}.csv'}", flush=True)
    if failed:
        print(f"Nicht vollständig: {failed} – Skript einfach erneut starten.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
