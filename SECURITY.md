# Security Policy

## Supported Versions

Nur die jeweils aktuellste Release-Version (Tag `vMAJOR.MINOR.PATCH` auf `main`)
erhaelt Security-Fixes. Aeltere Tags sind Snapshots und werden nicht rueckwirkend
gepatcht.

| Version | Supported |
|---|---|
| latest release | ✅ |
| aeltere Tags | ❌ |

## Vulnerability Reporting

Sicherheitsluecken bitte **nicht** oeffentlich in Issues melden. Stattdessen
direkt per E-Mail an:

- **Patrik Drexel** — <patrik.drexel@notavis.com>

Wir bestaetigen den Eingang innerhalb von **5 Werktagen** und geben eine
Einschaetzung inkl. Fix-Timeline binnen **10 Werktagen**.

## Secret Handling

Diese App **erwartet keine Secrets zur Laufzeit**. Sollten Sie einen Betriebs-
oder Deployment-Kontext einrichten, in dem Secrets benoetigt werden (z. B. eine
Reverse-Proxy-TLS-Konfiguration vor der Streamlit-UI), injizieren Sie diese
ausschliesslich ueber:

- Umgebungsvariablen (systemd `Environment=` oder `EnvironmentFile=`)
- Eine `.env`-Datei, die in `.gitignore` steht

**Niemals** Klartext-Secrets in Code, Commits, Log-Files oder GitHub-Issues.

## Abhaengigkeiten

Wir verfolgen Sicherheits-Advisories fuer die produktiven Runtime-Deps
(`streamlit`, `starlette`, `gpiozero`, `lgpio`, `pydantic`, `pyyaml`) und
issue-basierte Fixes im Rahmen normaler Releases.

## Incident Log

_(keine Eintraege)_
