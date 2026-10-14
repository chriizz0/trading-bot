# trading-bot

> **Aktueller Fokus (13.10.2026): kurzfristiges Index-CFD-Trading (US500, US100, DE40), Stunden bis wenige Tage, erst Demo.**
> Experiment **EXP-201** (`config/exp201.json`, vorregistriert): IMOM (Intraday-Momentum), IBS (Mean Reversion), DONCH (1h-Trendfolge).
> Workflow `Research EXP-201 (Intraday)` lädt Dukascopy-Daten und schreibt `reports/EXP-201.md`.
> Broker für Demo: Capital.com (Konto in Klärung). Der Bot handelt dort später selbst innerhalb harter Grenzen; Claude prüft täglich.
> Der Tages-ETF-Teil unten (EXP-101, Alpaca) ist geparkt.
>
> **Capital.com-Demo** (`src/tbot/capital.py`, nur Demo-URL): `.env.example` → `.env` kopieren und Demo-API-Schlüssel eintragen.
> `python scripts/capital_markets.py` schreibt Epics, Mindestgröße, Spread, Margin, Finanzierung und Handelszeiten nach
> `reports/capital-markets.json`; `--test-order` öffnet die kleinste Position mit Stop und schließt sie nach 10 s.

KI-überwachter Regel-Bot: **Backtest → Papertrading → (vielleicht) kleines Echtgeld.**
Neuanfang ab 13.10.2026. Der Backtest-Gedanke, die Datenprüfung und die
Lehren stammen aus `trading-research` (eingefroren); der Code ist neu und auf
Tagesdaten ausgelegt.

## Wie es funktioniert

```
22:15 UTC  1 Vorschlag     Bot holt Tagesdaten, rechnet Signal, schreibt proposals/<Tag>.json   (handelt nicht)
nachts     Claude-Review   prüft jede Order, schreibt reviews/<Tag>.json (approve/veto)          (REVIEW.md)
15:00 UTC  2 Ausführung    nur freigegebene Orders, nach harten Risikoregeln, ins Alpaca-Konto
Samstag    3 Wochenbericht Paper vs. Schattendepot ohne Veto vs. SPY                               (reports/)
```

Harte Regeln im Code (kein Review kann sie umgehen): nur Symbole des
Universums, kein Hebel (Cash statt Buying Power), Kill-Switch bei 25 %
Drawdown (danach nur Verkäufe, `journal/HALT` manuell löschen), Live-Modus
nur mit Secret `TBOT_LIVE_CONFIRM` und Kapitalobergrenze.

## Ablauf und Gates

1. **EXP-101** (`config/research.json`, vorregistriert 13.10.2026): TREND-SPY,
   GTAA5, GEM gegen SPY und 60/40. Workflow `Research EXP-101` starten →
   `reports/EXP-101.md`. Keine Parameteroptimierung.
2. Besteht eine Strategie das Gate → in `config/live.json` eintragen → Paper.
   Zum Technik-Test vorher möglich: `"strategy": "PIPELINE-TEST"` (60/40).
3. Echtgeld frühestens nach 3 Monaten Paper, 3 Rebalancings ohne Fehler,
   Abweichung zum Schattendepot ≤ 1,5 pp – und nur nach Freigabe durch Chris.

## Einrichtung

- Secrets: `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY` (Paper-Schlüssel).
- Variable `TBOT_MODE` nicht setzen (= paper).
- Lokal testen: `python -m unittest discover -s tests`.

## Grenzen

- Paper-Fills bei Alpaca sind idealisiert (keine Marktwirkung, keine Dividenden).
- Ausführung ca. 1–1,5 h nach Eröffnung, Backtest rechnet mit Eröffnungskurs.
- US-ETFs sind für deutsche Privatanleger bei EU-Brokern meist nicht kaufbar
  (PRIIPs). Für Echtgeld bei Alpaca prüfen oder auf UCITS-Pendants umstellen.
