<!--
  notavis-mipi-trigger — PR-Template
  Vollstaendig ausfuellen. PRs ohne diese Angaben werden zurueckgestellt.
  Regelquelle: SDS 05_Git-Workflow/04_pr-review-rules.md
-->

## Was

<!-- Kurzbeschreibung der Aenderung. 1-3 Zeilen. -->

## Warum

<!-- Motivation: Bug, Feature, Refactor, Doku, Chore. Verlinke Issue falls vorhanden. -->

## Wie getestet

<!--
  - Lokal / auf welchem Board?
  - Unit-Tests / Mocks?
  - HiL-Sanity-Check?
  - Manuelle Schritte?
-->

## Risiko

<!--
  Hardware-Risiko? Regression? Rollback-Plan?
  Bei Hardware-nahen Aenderungen: Auswirkung auf laufende Kamera / Trigger.
-->

## KI-Beteiligung

<!--
  - Modus (1 Pair-Programmer, 2 Autonom, 3 Recherche)
  - Welcher Agent (Perplexity Computer, Claude, GPT, ...)
  - Welche Files wurden agent-generiert?
  Regelquelle: SDS 04_AI-Agent-Rules/06_provenance-attribution.md
-->

## Checkliste

- [ ] PR-Body vollstaendig ausgefuellt
- [ ] Conventional Commit im Header
- [ ] `Co-Authored-by:` + `Agent-Mode:` Trailer bei agent-getriebenen Commits
- [ ] Diff &le; 400 Zeilen (oder Splitting-Begruendung im Body)
- [ ] Keine Secrets im Diff
- [ ] Kein Touch von `.github/workflows/` ohne explizite User-Approval (STOP S4)
- [ ] Kein Direct-Push auf `main` (STOP S1)
