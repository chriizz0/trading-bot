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


def fetch_day(sym: str, d: date, side: str, retries: int = 6) -> list[tuple]:
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
        time.sleep(1.5 * (k + 1))
    raise RuntimeError(f"Download fehlgeschlagen: {sym} {d} {side}")


def to_m30(rows: list[tuple]) -> pd.DataFrame:
    m1 = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    m1.index = pd.to_datetime(m1["timestamp"], unit="ms", utc=True)
    m30 = m1.resample("30min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    m30.insert(0, "timestamp", m30.index.as_unit("ms").asi8)
    return m30


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="2016-01-01")
    ap.add_argument("--to", dest="end", default=str(date.today() - timedelta(days=1)))
    ap.add_argument("--out", default="data/intraday")
    ap.add_argument("--only", nargs="*", default=list(SYMBOLS))
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    d0, d1 = date.fromisoformat(a.start), date.fromisoformat(a.end)
    days = [d0 + timedelta(n) for n in range((d1 - d0).days + 1)]
    days = [d for d in days if d.weekday() != 5]  # Samstag ohne Handel
    for name in a.only:
        for side in ("bid", "ask"):
            target = out / f"{name}-{side}.csv"
            if target.exists() and target.stat().st_size > 0:
                print(f"{target} vorhanden")
                continue
            t0 = time.time()
            with ThreadPoolExecutor(a.workers) as ex:
                parts = list(ex.map(lambda d: fetch_day(SYMBOLS[name], d, side), days))
            rows = [r for p in parts for r in p]
            if not rows:
                print(f"KEINE DATEN {name} {side}")
                return 1
            df = to_m30(rows)
            df.to_csv(target, index=False, float_format="%.3f")
            print(f"{name} {side}: {len(rows)} Minuten → {len(df)} 30-Min-Kerzen, "
                  f"{df.index[0]} – {df.index[-1]}, Close min/max {df.close.min():.1f}/{df.close.max():.1f}, "
                  f"{time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
