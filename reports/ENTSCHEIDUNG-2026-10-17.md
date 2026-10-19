# Entscheidung 2026-10-17 nach EXP-101, EXP-201, EXP-301

Getestet (alle vorregistriert, keine Parameteroptimierung, nach Kosten):

| Experiment | Idee | Ergebnis |
|---|---|---|
| EXP-201 | Intraday/Swing mit Index-CFDs (IMOM, IBS, DONCH; US500/US100) | alles negativ oder Zufall; Spread frisst 18–40 % der Bewegung; DE40-Daten unbrauchbar |
| EXP-301 | Diversifiziertes Trendfolgen, 12 Märkte, Hebel ~1,7 | Futures-Kosten: Sharpe 0,27 (Gate 0,4) · CFD-Kosten: Sharpe −0,47, −60 % Drawdown |
| EXP-101 | ETF-Strategien, monatlich, ohne Hebel | knapp gescheitert; TREND-SPY: Sharpe 0,68 vs. SPY 0,66, Drawdown −25 % vs. −51 %, aber CAGR 8,1 % < 60/40 8,3 % |
| Vergleich | SPY Buy & Hold / 60-40 | Sharpe 0,66–0,81 / 0,73 – schwer zu schlagen |

Schlüsse:
1. CFDs sind für systematisches Trading ungeeignet: kurz → Spread, länger → Übernachtgebühr
   (Capital.com: Long zahlt Benchmark + Aufschlag, Short erhält Benchmark − Aufschlag, variabel je Markt.
   Das EXP-301-Kostenmodell rechnet vereinfacht ~4 % p.a. Kosten auf das gesamte Exposure – eine Modellannahme, für Shorts konservativ;
   Korrektur nach Audit 19.10.).
2. Keine getestete Strategie hat sich Echtgeld verdient. Gates werden nicht nachträglich gelockert.
3. Bestes Chance-Risiko-Verhältnis im Test: breit gestreut passiv (Welt-/S&P-ETF bzw. 60/40).

Weiter:
- Capital.com-Anbindung und CFD-Pläne ruhen.
- Lernprojekt: TREND-SPY als **Forward-Test ohne Broker** (monatliches Signal wird nur protokolliert,
  ausdrücklich als „Gate nicht bestanden“ gekennzeichnet). Nach 12 Monaten Live-Daten neu bewerten.
- Neue Ideen nur mit neuer Experiment-ID und vorher festgelegten Grenzen.
