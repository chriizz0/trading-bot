# Claude-Review eines Order-Vorschlags

Der Bot handelt **nur**, was hier ausdrücklich freigegeben wird. Fehlt ein
Review oder passt es nicht zum Vorschlag (SHA-256), wird nichts gehandelt.

## Ablauf (täglich nach `1 Vorschlag nach Börsenschluss`)

1. `git pull`, neuesten Vorschlag `proposals/JJJJ-MM-TT.json` öffnen.
2. Gibt es schon `reviews/<gleiches Datum>.json` oder ist `orders` leer → fertig.
3. Jede Order einzeln prüfen (Checkliste unten). Signal **selbst nachrechnen**
   aus `inputs_monthly_adj_closes` und `strategy_params` – nicht dem Bot glauben.
4. `reviews/<Datum>.json` schreiben, committen, pushen. Ausführung folgt am
   nächsten Handelstag um 15:00 UTC.

## Checkliste je Order (Ein- und Ausstieg)

| Prüfung | Veto-Code bei Verstoß |
|---|---|
| Signal nachgerechnet: SMA-/Momentum-Werte ergeben genau dieses Ziel | `rule_mismatch` |
| Daten plausibel: letzter Schlusskurs vs. Vormonat, keine Sprünge ohne Erklärung, `data_quality` ok | `data_error` |
| Ordergröße passt zu Ziel × Kontowert, Verkäufe vor Käufen, kein Hebel, nur Universum | `risk_breach` |
| ETF-Ereignisse: Split, Fondsschließung, Indexwechsel, außergewöhnliche Ausschüttung (Websuche) | `corporate_action` |
| Markt: Börsenschließung, Handelsaussetzung, Systemstörung am Ausführungstag (Websuche) | `market_disruption` |

**Kein Veto aus Bauchgefühl oder Marktmeinung.** Eine Einschätzung zur
Marktlage gehört in `advisory` (wird protokolliert und im Wochenbericht
gegen das Ergebnis ausgewertet, verhindert aber keinen Trade). Nur so bleibt
messbar, ob die KI-Prüfung einen Mehrwert hat.

## Format `reviews/JJJJ-MM-TT.json`

```json
{
  "proposal_sha256": "<sha256 aus dem Vorschlag>",
  "reviewer": "claude",
  "reviewed_at": "2026-10-30T23:40:00Z",
  "signal_recomputed": true,
  "decisions": [
    {"order_id": "SPY-sell", "decision": "approve", "reason": "Kurs 612 < SMA10M 618 → Cash laut Regel"},
    {"order_id": "BIL-buy", "decision": "veto", "reason_code": "data_error", "reason": "…"}
  ],
  "advisory": "optional: Marktmeinung, ohne Wirkung auf die Ausführung",
  "sources": ["https://…"]
}
```
