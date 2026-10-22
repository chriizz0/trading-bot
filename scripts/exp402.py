"""EXP-402: Schlagzeilen → günstiges Modell → Bewertung je Aktie; Auswertung gegen die Rendite des nächsten Tages.
  python scripts/exp402.py predict   (Actions, Mo–Fr nach US-Schluss)
  python scripts/exp402.py score
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
CFG = json.loads((ROOT / "config/exp402.json").read_text())
PRED, OUT = ROOT / "predictions/exp402", ROOT / "reports/exp402"

PROMPT = """Du bewertest Finanz-Schlagzeilen. Für jede Aktie: Wie wirken die Schlagzeilen der letzten 24 Stunden
voraussichtlich auf den Kurs am NÄCHSTEN Handelstag (relativ zum Gesamtmarkt)? score von -1 (sehr negativ) bis 1 (sehr positiv),
0 wenn irrelevant oder schon bekannt. Sei sparsam mit großen Werten.

{news}

Antworte NUR mit einem JSON-Objekt, ohne Text davor oder danach: {{"scores": {{"TICKER": 0.0, ...}}, "notes": {{"TICKER": "max. 6 Wörter, nur für score ungleich 0"}}}}"""


def debug() -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    info = {}
    for name in SOURCES:
        try:
            items = _rss(SOURCES[name].format(sym="AAPL"))
            info[name] = {"items": len(items), "last_24h": len(headlines("AAPL", since, name)),
                          "beispiel": items[0][1][:90] if items else None}
        except Exception as e:  # noqa: BLE001
            info[name] = {"fehler": type(e).__name__}
    if os.environ.get("ANTHROPIC_API_KEY"):
        from tbot.llm import LLMError, ask_anthropic
        try:
            info["anthropic"] = "OK: " + ask_anthropic("Antworte nur mit OK", max_tokens=5)[:10]
            fs = sorted(PRED.glob("*.json"))
            if fs:  # Parse-Test mit gespeicherten Schlagzeilen (wird NICHT als Prognose gespeichert)
                from tbot.llm import extract_json
                hl = {k: v for k, v in json.loads(fs[-1].read_text())["headlines"].items() if v}
                for m in CFG["models"]:
                    raw = ask_anthropic(PROMPT.format(news="\n".join(f"{k}: " + " | ".join(v) for k, v in hl.items())), model=m, max_tokens=4000)
                    try:
                        info[f"parse_test {m}"] = f"OK, {len(extract_json(raw).get('scores', {}))} Werte bewertet"
                    except Exception as e:  # noqa: BLE001
                        info[f"parse_test {m}"] = f"FEHLER {type(e).__name__}: {raw[:300]}"
        except LLMError as e:
            info["anthropic"] = str(e)[:200]
    else:
        info["anthropic"] = "kein Schlüssel"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "debug.json").write_text(json.dumps(info, indent=1, ensure_ascii=False))
    print(info)
    return 0


UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 Version/17.5 Safari/605.1.15"}
SOURCES = {
    "yahoo_rss": "https://feeds.finance.yahoo.com/rss/2.0/headline?s={sym}&region=US&lang=en-US",
    "google_news": "https://news.google.com/rss/search?q={sym}+stock+when:1d&hl=en-US&gl=US&ceid=US:en",
}


def _rss(url: str) -> list[tuple[pd.Timestamp, str]]:
    import urllib.request
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        root = ET.fromstring(r.read())
    out = []
    for it in root.iter("item"):
        t, d = it.findtext("title"), it.findtext("pubDate")
        if t and d:
            out.append((pd.Timestamp(parsedate_to_datetime(d)).tz_convert("UTC"), t.strip()))
    return out


def headlines(sym: str, since: datetime, source: str | None = None) -> list[str]:
    for name in ([source] if source else SOURCES):
        try:
            items = _rss(SOURCES[name].format(sym=sym))
        except Exception:  # noqa: BLE001
            continue
        hs = [t for ts, t in sorted(items, reverse=True) if ts >= pd.Timestamp(since)]
        if hs or source:
            return list(dict.fromkeys(hs))[:6]
    return []


def signal_day(now: datetime):
    """Handelstag, dessen US-Schluss das Signal abschließt. Während der US-Handelszeit: kein Signal."""
    ny = pd.Timestamp(now).tz_convert("America/New_York")
    t = ny.hour * 60 + ny.minute
    if t >= 16 * 60:
        d = ny.normalize()
    elif t < 9 * 60 + 15:
        d = ny.normalize() - pd.offsets.BDay(1)
    else:
        return None
    return (d - pd.offsets.BDay(1) if d.dayofweek >= 5 else d).date()


def predict() -> int:
    now = datetime.now(timezone.utc)
    sd = signal_day(now)
    if sd is None:
        print("US-Markt offen – kein Signal (sonst Vorgriff auf die Eröffnung).")
        return 0
    day = sd.isoformat()
    if now.date() > pd.Timestamp(CFG["end"]).date():
        print("EXP-402 beendet.")
        return 0
    out = PRED / f"{day}.json"
    if out.exists():
        return 0
    news = {s: headlines(s, now - timedelta(hours=24)) for s in CFG["universe"]}
    with_news = {s: h for s, h in news.items() if h}
    models = [m.strip() for m in os.environ.get("ANTHROPIC_MODELS", ",".join(CFG["models"])).split(",") if m.strip()]
    runs = {}
    if with_news and os.environ.get("ANTHROPIC_API_KEY"):
        from tbot.llm import LLMError, ask_anthropic, extract_json
        text = "\n".join(f"{s}: " + " | ".join(h) for s, h in with_news.items())
        for model in models:  # alle Modelle bekommen exakt denselben Text
            raw, scores, notes = "", {}, {}
            try:
                raw = ask_anthropic(PROMPT.format(news=text), model=model, max_tokens=4000)
                data = extract_json(raw)
                scores = {s: max(-1.0, min(1.0, float(v))) for s, v in data.get("scores", {}).items() if s in with_news}
                notes = data.get("notes", {})
            except LLMError as e:  # Meldung enthält garantiert keine Header/Schlüssel
                notes = {"_fehler": str(e)[:300]}
            except (ValueError, KeyError) as e:
                notes = {"_fehler": f"Antwort nicht auswertbar: {type(e).__name__}", "_antwort_anfang": raw[:400]}
            runs[model] = {"scores": scores, "notes": notes}
    elif with_news:
        print("ANTHROPIC_API_KEY fehlt – nur Schlagzeilen gespeichert.")
    PRED.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"experiment": "EXP-402", "signal_date": day, "created_at": now.isoformat(timespec="seconds"),
                               "headlines": news, "runs": runs}, indent=1, ensure_ascii=False))
    print(f"{day}: {len(with_news)} Werte mit Nachrichten; bewertet: " + ", ".join(f"{m} {len(r['scores'])}" for m, r in runs.items()))
    if not with_news or any("_fehler" in r["notes"] or not r["scores"] for r in runs.values()) or len(runs) < len(models):
        print("WARNUNG: Lauf unvollständig – Workflow wird als fehlgeschlagen markiert (GitHub schickt eine E-Mail).")
        return 1
    return 0


def _metrics(x: pd.DataFrame) -> dict:
    days = [g for _, g in x.groupby("date") if len(g) >= 3 and g.score.nunique() > 1]
    ics = {g.date.iloc[0]: float(g.score.rank().corr(g.alpha.rank())) for g in days}
    rng = np.random.default_rng(0)
    null = [np.mean([pd.Series(rng.permutation(g.score.values)).rank().corr(g.alpha.rank().reset_index(drop=True)) for g in days])
            for _ in range(2000)] if days else []
    ls = {d: float(g.loc[g.score > 0, "alpha"].mean() - g.loc[g.score < 0, "alpha"].mean())
          for d, g in x.groupby("date") if (g.score > 0).any() and (g.score < 0).any()}
    neg, pos = x[x.score < 0], x[x.score > 0]
    return {"signals": int(len(x)), "days": int(x.date.nunique()),
            "ic_mean": float(np.mean(list(ics.values()))) if ics else None, "ic_by_day": ics,
            "perm_p": float(np.mean(np.array(null) >= np.mean(list(ics.values())))) if ics else None,
            "ls_by_day": ls, "neg_mean_alpha": float(neg.alpha.mean()) if len(neg) else None,
            "pos_mean_alpha": float(pos.alpha.mean()) if len(pos) else None,
            "ic_close_close_info": float(np.mean([g.score.rank().corr(g.alpha_close_close.rank()) for g in days])) if days else None}


def score() -> int:
    import yfinance as yf
    files = sorted(PRED.glob("*.json"))
    rows = []
    if files:
        syms = CFG["universe"] + [CFG["benchmark"]]
        raw = yf.download(syms, start="2026-10-01", auto_adjust=True, progress=False)
        px, op = raw["Close"], raw["Open"]
        px.index = op.index = pd.DatetimeIndex(px.index).tz_localize(None)
        for f in files:
            p = json.loads(f.read_text())
            d = pd.Timestamp(p["signal_date"])
            if d not in px.index:
                continue
            i = px.index.get_loc(d)
            if i + 1 >= len(px):
                continue
            r = px.iloc[i + 1] / op.iloc[i + 1] - 1          # handelbar: Eröffnung → Schluss nächster Tag
            r2 = px.iloc[i + 1] / px.iloc[i] - 1             # informativ: Schluss → Schluss (enthält nicht handelbare Nachtlücke)
            b = CFG["benchmark"]
            runs = p.get("runs") or ({p["model"]: {"scores": p.get("scores", {})}} if p.get("model") else {})
            for model, run in runs.items():
                for s, v in run.get("scores", {}).items():
                    if v != 0:
                        rows.append({"model": model, "date": p["signal_date"], "symbol": s, "score": v,
                                     "alpha": float(r[s] - r[b]), "alpha_close_close": float(r2[s] - r2[b])})
    res = {"updated": datetime.now(timezone.utc).date().isoformat(), "signals": len(rows), "models": {}}
    if rows:
        x = pd.DataFrame(rows)
        res["models"] = {m: _metrics(g) for m, g in x.groupby("model")}
        res["signals_list"] = x.round(5).to_dict("records")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "score.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print({m: {k: v for k, v in r.items() if k not in ("ic_by_day", "ls_by_day")} for m, r in res["models"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit({"predict": predict, "score": score, "debug": debug}[sys.argv[1]]())
