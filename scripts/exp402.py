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

Antworte NUR mit JSON: {{"scores": {{"TICKER": 0.0, ...}}, "notes": {{"TICKER": "max. 8 Wörter"}}}}"""


def headlines(sym: str, since: datetime) -> list[str]:
    import yfinance as yf
    out = []
    for n in yf.Ticker(sym).news or []:
        c = n.get("content", n)
        ts = c.get("pubDate") or c.get("providerPublishTime")
        t = pd.Timestamp(ts, unit="s", tz="UTC") if isinstance(ts, (int, float)) else pd.Timestamp(ts)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        if t >= since and c.get("title"):
            out.append(c["title"].strip())
    return out[:6]


def predict() -> int:
    now = datetime.now(timezone.utc)
    day = now.date().isoformat()
    if now.date() > pd.Timestamp(CFG["end"]).date():
        print("EXP-402 beendet.")
        return 0
    out = PRED / f"{day}.json"
    if out.exists():
        return 0
    news = {s: headlines(s, now - timedelta(hours=24)) for s in CFG["universe"]}
    with_news = {s: h for s, h in news.items() if h}
    scores, notes, model = {}, {}, None
    if with_news and os.environ.get("ANTHROPIC_API_KEY"):
        from tbot.llm import ask_anthropic, extract_json
        text = "\n".join(f"{s}: " + " | ".join(h) for s, h in with_news.items())
        data = extract_json(ask_anthropic(PROMPT.format(news=text), max_tokens=1500))
        scores = {s: max(-1.0, min(1.0, float(v))) for s, v in data.get("scores", {}).items() if s in with_news}
        notes, model = data.get("notes", {}), os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")
    elif with_news:
        print("ANTHROPIC_API_KEY fehlt – nur Schlagzeilen gespeichert.")
    PRED.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"experiment": "EXP-402", "signal_date": day, "created_at": now.isoformat(timespec="seconds"),
                               "model": model, "headlines": news, "scores": scores, "notes": notes}, indent=1, ensure_ascii=False))
    print(f"{day}: {len(with_news)} Werte mit Nachrichten, {len(scores)} bewertet")
    return 0


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
            for s, v in p.get("scores", {}).items():
                if v != 0:
                    rows.append({"date": p["signal_date"], "symbol": s, "score": v, "alpha": float(r[s] - r[b]),
                                 "alpha_close_close": float(r2[s] - r2[b])})
    res = {"updated": datetime.now(timezone.utc).date().isoformat(), "signals": len(rows)}
    if rows:
        x = pd.DataFrame(rows)
        days = [g for _, g in x.groupby("date") if len(g) >= 3 and g.score.nunique() > 1]
        ics = {g.date.iloc[0]: float(g.score.rank().corr(g.alpha.rank())) for g in days}
        rng = np.random.default_rng(0)
        null = [np.mean([pd.Series(rng.permutation(g.score.values)).rank().corr(g.alpha.rank().reset_index(drop=True)) for g in days])
                for _ in range(2000)] if days else []
        ls = {d: float(g.loc[g.score > 0, "alpha"].mean() - g.loc[g.score < 0, "alpha"].mean())
              for d, g in x.groupby("date") if (g.score > 0).any() and (g.score < 0).any()}
        neg = x[x.score < 0]
        res.update({"ic_mean": float(np.mean(list(ics.values()))) if ics else None, "ic_by_day": ics,
                    "perm_p": float(np.mean(np.array(null) >= np.mean(list(ics.values())))) if ics else None,
                    "ls_by_day": ls, "neg_mean_alpha": float(neg.alpha.mean()) if len(neg) else None,
                    "pos_mean_alpha": float(x[x.score > 0].alpha.mean()) if (x.score > 0).any() else None,
                    "ic_close_close_info": float(np.mean([g.score.rank().corr(g.alpha_close_close.rank()) for g in days])) if days else None,
                    "signals_list": x.round(5).to_dict("records")})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "score.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print({k: v for k, v in res.items() if k not in ("signals_list", "ic_by_day", "ls_by_day")})
    return 0


if __name__ == "__main__":
    raise SystemExit({"predict": predict, "score": score}[sys.argv[1]]())
