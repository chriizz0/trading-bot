"""Tagesdaten über yfinance laden (läuft in GitHub Actions, nicht lokal nötig)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tbot.data import load_csv, sha256_file, validate  # noqa: E402


def fetch(symbol: str, start: str):
    import yfinance as yf

    df = yf.download(symbol, start=start, auto_adjust=False, actions=False, progress=False, multi_level_index=False)
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close",
                            "Adj Close": "adj_close", "Volume": "volume"})
    df.index.name = "date"
    return df[["open", "high", "low", "close", "adj_close", "volume"]].dropna(how="all")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", required=True)
    ap.add_argument("--start", default="2000-01-01")
    ap.add_argument("--out", default="data/raw")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest, failed = {"fetched_at": datetime.now(timezone.utc).isoformat(), "source": "yfinance", "files": {}}, []
    for s in a.symbols:
        df = fetch(s, a.start)
        p = out / f"{s}.csv"
        df.to_csv(p, float_format="%.6f")
        rep = validate(load_csv(p), s)
        manifest["files"][s] = {"sha256": sha256_file(p), "rows": rep.rows, "first": rep.first, "last": rep.last,
                                "errors": rep.errors, "warnings": rep.warnings}
        print(s, rep.rows, rep.first, rep.last, "OK" if rep.ok else rep.errors, rep.warnings or "")
        if not rep.ok:
            failed.append(s)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
