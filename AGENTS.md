# Regeln für KI-Agenten (Claude, Codex, ChatGPT)

- Sprache: Deutsch. Token sparen: erst README.md, dann nur die betroffene Datei.
- `config/research.json` ist vorregistriert. Parameter, Perioden, Kosten oder Gates
  **nie** nachträglich ändern. Neue Idee = neue Experiment-ID in neuer Datei.
- Keine Strategie in `config/live.json`, die ihr Gate nicht bestanden hat
  (Ausnahme: `PIPELINE-TEST` zum Technik-Test im Paper-Konto).
- `TBOT_MODE=live` / `TBOT_LIVE_CONFIRM` nur nach ausdrücklicher Anweisung von Chris.
- Reviews nach `REVIEW.md`. Kein Veto aus Marktmeinung.
- Keine API-Schlüssel ins Repo, in Commits oder Notizen.
- Negative Ergebnisse unverändert dokumentieren.
- Vor jedem Push: `python -m unittest discover -s tests`.
