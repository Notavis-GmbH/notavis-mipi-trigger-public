# Changelog

Alle nennenswerten Aenderungen an diesem Projekt werden hier dokumentiert.
Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung nach [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Added

- Docker-Unterstuetzung fuer die Streamlit-Web-UI: `Dockerfile` (Multi-Stage,
  Base-Image `python:3.12-slim-trixie`, kompiliert `lgpio` aus dem Quellcode
  via SWIG/build-essential), `docker-compose.yml`-Beispiel mit
  GPIO-Device-Passthrough-Anleitung fuer CM5/Pi 5, sowie `deploy/DOCKER.md`
  mit Details zu Multi-Arch-Builds (linux/amd64, linux/arm64), gpiochip-
  Ermittlung und Troubleshooting. Die PySide6-Desktop-UI ist bewusst nicht
  Teil des Images (siehe Begruendung in `deploy/DOCKER.md`).
- CI-Workflow `.github/workflows/docker.yml`: baut das Docker-Image bei
  jedem relevanten Push/PR fuer linux/amd64 und linux/arm64, inkl.
  `hadolint`-Lint und `docker compose config`. Bei Push nach `main` bzw.
  einem Versions-Tag `vX.Y.Z` wird das Image zusaetzlich nach
  `ghcr.io/notavis-gmbh/notavis-mipi-trigger-public` veroeffentlicht;
  README-Abschnitt mit Pull-Kommando und CI-/Image-Badges ergaenzt.

## [0.1.2] — 2026-08-10

### BREAKING CHANGE

Alle Sensor-spezifischen Features wurden entfernt. Das Repository ist jetzt ein
**reiner GPIO/PWM-Trigger** — es findet keine Kamera-Kommunikation, keine
Sensor-Erkennung und keine V4L2-Interaktion mehr statt. Zurueck zur Ur-Idee:
einen Pin auf einem Raspberry Pi als externen Kamera-Trigger nutzen.

### Removed

- `SensorController`, `SensorParams`, `SensorVendor`, `SensorPixelFormat` und
  alle zugehoerigen Enums / Konstanten aus `vc_trigger/models.py`.
- Module `vc_trigger.sensor_catalog_loader`, `vc_trigger.sensor_controller`,
  `vc_trigger.sensor_profiles_loader` inklusive aller Tests.
- Verzeichnis `src/vc_trigger/sensor_profiles/` (25 Sensor-YAMLs).
- Sensor-Erkennungs-Kaskade (`libcamera`, V4L2, Registry).
- `pyyaml`-Abhaengigkeit (kein YAML-Loader mehr noetig).

### Fixed

- Wheel-Build-Fehler `ValueError: A second file is being added to the wheel
  archive at the same path: vc_trigger/sensor_profiles/OV9281.yaml` unter Python
  3.13 auf Debian 13 Trixie. Ursache war die Kombination aus
  `[tool.hatch.build.targets.wheel] packages` und `[tool.hatch.build.targets.wheel.force-include]`
  in `pyproject.toml`. Mit dem Wegfall des Sensor-Codes ist die Klausel obsolet.

### Changed

- Lizenz von „Proprietary — NOTAVIS GmbH internal" auf **MIT** umgestellt.
- Desktop-UI-Titel: „VC MIPI Trigger" → „NOTAVIS Trigger".
- Streamlit-UI-Titel identisch angepasst.
- `pyproject.toml`: `Development Status :: 4 - Beta`, Python 3.13 in `classifiers`
  aufgenommen.

### Verified

- Testsuite: 22/22 gruen (`QT_QPA_PLATFORM=offscreen VC_TRIGGER_MOCK=1 pytest`).
- Wheel-Build: `notavis_mipi_trigger-0.1.2-py3-none-any.whl` (17 710 Bytes),
  keine Duplicate-Paths.

## [0.1.1] — 2026-08-10 — YANKED

**Nicht verwenden.** Wheel-Build schlaegt unter Python 3.13 auf Debian 13
Trixie mit `Duplicate-Path`-Fehler fehl (siehe v0.1.2 → Fixed).

## [0.1.0] — 2026-08-10

- Erstveroeffentlichung mit Sensor-Detection-Kaskade, Streamlit-UI, PySide6-UI
  und 25-Sensor-Katalog. Nur historisch dokumentiert; siehe interne
  `notavis-mipi-trigger`-Historie.

[0.1.2]: https://github.com/Notavis-GmbH/notavis-mipi-trigger-public/releases/tag/v0.1.2
[0.1.1]: https://github.com/Notavis-GmbH/notavis-mipi-trigger-public/releases/tag/v0.1.1
[0.1.0]: https://github.com/Notavis-GmbH/notavis-mipi-trigger-public/releases/tag/v0.1.0
