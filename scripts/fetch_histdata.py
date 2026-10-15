"""Ersatzquelle für EXP-201: HistData.com 1-Minuten-Kerzen (ASCII, Bid-Kurse).

Dukascopy sperrt seit 14./15.10.2026 (HTTP 503, auch für private Anschlüsse).
HistData liefert CFD-Indizes (SPXUSD, NSXUSD, GRXEUR) als Jahres-ZIPs, das laufende
Jahr monatsweise. Zeitstempel: EST ohne Sommerzeit (= UTC-5).
Nur Bid → wird als Bid UND Ask gespeichert (Mid = Bid); der Spread wird im
Backtest ohnehin vollständig über das Kostenmodell abgezogen."""
from __future__ import annotations

import argparse
import io
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

PAIRS = {"US500": "spxusd", "US100": "nsxusd", "DE40": "grxeur"}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
BASE = "https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes"


def _get(url: str, data: bytes | None = None, referer: str | None = None) -> bytes:
    h = {"User-Agent": UA}
    if referer:
        h["Referer"] = referer
    for k in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=120) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(5 * (k + 1))
    raise RuntimeError(f"{url}: {err}")


def download(pair: str, year: int, month: int | None) -> pd.DataFrame:
    page = f"{BASE}/{pair}/{year}" + (f"/{month}" if month else "")
    html = _get(page).decode("utf-8", "replace")
    form = dict(re.findall(r'<input[^>]*?(?:id|name)="(tk|date|datemonth|platform|timeframe|fxpair)"[^>]*?value="([^"]*)"', html))
    if "tk" not in form:
        raise RuntimeError(f"kein Download-Token auf {page}")
    raw = _get("https://www.histdata.com/get.php", urllib.parse.urlencode(form).encode(), referer=page)
    z = zipfile.ZipFile(io.BytesIO(raw))
    name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
    df = pd.read_csv(z.open(name), sep=";", header=None, names=["dt", "open", "high", "low", "close", "vol"],
                     dtype={"dt": str})
    ts = pd.to_datetime(df["dt"], format="%Y%m%d %H%M%S") + pd.Timedelta(hours=5)  # EST fix → UTC
    df.index = ts.dt.tz_localize("UTC")
    return df[["open", "high", "low", "close"]]


def to_m30(m1: pd.DataFrame) -> pd.DataFrame:
    m30 = m1.resample("30min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    m30.insert(0, "timestamp", m30.index.as_unit("ms").asi8)
    return m30


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-year", type=int, default=2016)
    ap.add_argument("--out", default="data/intraday")
    a = ap.parse_args()
    out = Path(a.out)
    cache = out / "histdata"
    cache.mkdir(parents=True, exist_ok=True)
    today = date.today()
    jobs = [(y, None) for y in range(a.from_year, today.year)] + [(today.year, m) for m in range(1, today.month)]
    for name, pair in PAIRS.items():
        parts = []
        for y, m in jobs:
            f = cache / f"{name}-{y}{'-%02d' % m if m else ''}.csv"
            if not f.exists():
                try:
                    to_m30(download(pair, y, m)).to_csv(f, index=False, float_format="%.3f")
                except Exception as e:  # noqa: BLE001
                    print(f"FEHLER {name} {y}-{m}: {e}", flush=True)
                    continue
                time.sleep(2)
            d = pd.read_csv(f)
            print(f"{name} {y}{'-%02d' % m if m else ''}: {len(d)} Kerzen, Close {d.close.min():.1f}–{d.close.max():.1f}", flush=True)
            parts.append(d)
        if not parts:
            return 1
        df = pd.concat(parts).drop_duplicates("timestamp").sort_values("timestamp")
        for side in ("bid", "ask"):
            df.to_csv(out / f"{name}-{side}.csv", index=False)
        print(f"== {name}: {len(df)} Kerzen", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
