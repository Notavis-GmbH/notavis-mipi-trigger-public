# Changelog

Alle nennenswerten Aenderungen an diesem Projekt werden hier dokumentiert.

Format: [Keep a Changelog 1.1](https://keepachangelog.com/en/1.1.0/).
Version: [Semantic Versioning 2.0](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-08-06

### Fixed

- **Streamlit gzip middleware crash (HTTP 500 on every request).** `starlette`
  wird jetzt auf `>=0.47,<0.48` gepinnt. Ab `starlette 1.4.0` erwartet
  `GZipResponder.__init__()` ein `thread_minimum_size`-Argument, das Streamlit
  1.61 nicht setzt — jeder Request scheitert dann in
  `starlette_gzip_middleware.py`. Verifiziert auf `UniversitySidney1` (CM5,
  Trixie): mit dem Pin startet der Service sauber und liefert die UI aus.
- **Streamlit-Skript-Import: `ImportError: attempted relative import with no
  known parent package`.** `streamlit run src/vc_trigger/ui.py` fuehrt die
  Datei als Top-Level-Skript aus; die drei relativen Imports
  (`from .controller`, `from .logging_setup`, `from .models`) hatten dabei
  keinen Paket-Kontext. Auf absolute Imports (`from vc_trigger.controller`,
  usw.) umgestellt.
- **`deploy/vc-trigger.service` an Notavis-Dev-Board-Baseline angeglichen.**
  User/Group von `notavis` auf `raspberrypi` gesetzt (Standard-User laut
  Project-Skill `notavis-dev-board-access`), `ExecStart` auf
  `.venv/bin/python` gezogen, Pfade auf `/home/raspberrypi/vc-trigger`
  vereinheitlicht.
- **`tests/test_desktop_ui_catalog.py` uebersprang nicht sauber ohne PySide6.**
  Modul importierte PySide6 im Top-Level, wodurch `pytest` auf einem `[dev]`-
  only-Setup mit `ImportError` abbrach. Jetzt `pytest.importorskip("PySide6")`
  am Modul-Anfang analog zu `test_desktop_ui.py`.

### Changed

- **`deploy/DEPLOY.md` und `README.md`-Schnellstart:** venv-basierte
  Installation ist jetzt der dokumentierte Standard (nicht mehr eine
  Alternative zu `pip --break-system-packages`). Explizite Warnung, dass
  `--system-site-packages` einen `google.protobuf`-Konflikt ausloest.

## [0.1.0] - 2026-08-04

Initialer Release. Umfasst das Repository-Skeleton, den Kern-Trigger-Controller,
zwei gleichwertige Frontends (Streamlit + PySide6-Desktop) auf GPIO 18, die
systemd-Deployment-Unit, den Sensor-Test-Tab mit V4L2-Anbindung sowie die
3-Wege-Sensor-Detection-Cascade (live / catalog / unknown) mit einem
25-Sensor-VC-MIPI-Katalog. Live verifiziert auf `UniversitySidney1` (Raspberry
Pi CM5, Debian 13 Trixie, aarch64) mit OV9281 an `/dev/v4l-subdev2`.

### Added

- **Repository-Skeleton:** README, AGENTS.md, SECURITY.md, LICENSE.internal.md,
  `pyproject.toml` (hatchling), `.gitignore`, PR-Template.
- **`vc_trigger` Core-Package:** thread-safe `TriggerController` (single-shot +
  PWM auf GPIO 18, `gpiozero` + `lgpio`, `SIGINT`/`SIGTERM`/`atexit`-Cleanup),
  Pydantic-Parameter-Modelle mit harten Grenzen (1–200 Hz, 0–100 %,
  0.1–1000 ms), strukturiertes Logging-Setup.
- **Pytest-Suite** mit Mock-PinFactory (kein Board fuer Tests noetig).
- **Streamlit-UI** (`vc_trigger.ui`): Sprachumschaltung Deutsch/Englisch
  (Standard Deutsch), getrennte Ansichten fuer Einzel-Puls und PWM-Modus,
  explizite „Anwenden"-Buttons (kein Trigger bei Slider-Move), Status-Anzeige
  inkl. aktueller PWM-Parameter und letzter Fehlermeldung, Mock-Modus per
  `VC_TRIGGER_MOCK=1` fuer Entwicklung ohne Board.
- **Console-Script `vc-trigger-ui`** ueber `pyproject.toml` registriert.
- **Systemd-Unit `deploy/vc-trigger.service`** fuer Autostart der UI auf dem
  CM5: User `notavis`, `SupplementaryGroups=gpio`, gehaertet
  (`NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome=read-only`,
  `StateDirectory=vc-trigger` fuer Streamlits `~/.streamlit`),
  `Restart=on-failure`.
- **`deploy/DEPLOY.md`:** Schritt-fuer-Schritt-Anleitung fuer Erstinstallation,
  Service-Aktivierung und LED-Smoke-Test auf `UniversitySidney1`.
- **PySide6-Desktop-UI** (`vc_trigger.desktop_ui`): native Qt-App als
  alternativer Frontend zum Streamlit-Web-UI. `QMainWindow` mit
  Modus-Umschalter, Slider+SpinBox fuer Pulsdauer/Frequenz/Duty Cycle,
  DE/EN-Sprachumschaltung ueber Menu, Status-Panel mit Modus / aktiver PWM /
  letzter Fehlermeldung. `QThread`-Worker fuer den blockierenden
  Single-Shot-Puls (UI bleibt reaktiv), 200 ms `QTimer` fuer Status-Refresh,
  sauberes Shutdown ueber `closeEvent`. Beide UIs teilen sich denselben
  `TriggerController` und erzeugen identische Signale auf GPIO 18.
- **Optional-Extra `[desktop]`** (`PySide6>=6.7`) und Console-Script
  `vc-trigger-desktop` in `pyproject.toml`.
- **`tests/test_desktop_ui.py`:** 14 Tests fuer Widget-Konstruktion,
  Slider-SpinBox-Sync, Sprachumschaltung, Controller-Kopplung und
  Worker-Fehlerpfade (headless via `QT_QPA_PLATFORM=offscreen`).
- **Sensor-Test-Tab** in der Desktop-UI (`vc_trigger.desktop_ui`):
  Top-Level-`QTabWidget`-Refactor mit den Tabs *Trigger* und *Sensor-Test*.
  Der Sensor-Tab bindet die VC-MIPI-Sensor-Controls (`exposure`,
  `analogue_gain`, `trigger_mode`, Pixel-Format) via `v4l2-ctl` an das lokale
  Subdev `/dev/v4l-subdev2` und schreibt Capture-Frames nach
  `~/vc-trigger-logs/`. Read-back reflektiert den Hardware-Zustand zurueck in
  die Widgets; Fehler werden im Log-View mit V4L2-Wortlaut geloggt.
- **`SensorController`** (`vc_trigger.sensor_controller`): Subprocess-Wrapper
  um `v4l2-ctl` mit deterministischem Mock-Backend, Timeout,
  User-Switching (`run_as_user`) und Format-Parser.
- **`SensorParams` / `SensorPixelFormat` / `SensorVendor`** Pydantic-Modelle
  mit konservativen Grenzen (Exposure 1..1e6 us, Gain 0..12000,
  TriggerMode 0..7) — der Treiber kann strengere Limits enforcen, diese
  werden verbatim in der UI angezeigt.
- **CM5-Board-Voraussetzungen:** README-Abschnitt fuer frischen Trixie-CM5
  (APT-Pakete fuer den `lgpio`-Wheel-Build, Verweis auf die Notavis-Engineering-
  Standards).
- **Sensor-Profil-Registry** (`vc_trigger.sensor_profile_loader`):
  YAML-basierte Live-Profile unter `src/vc_trigger/sensor_profiles/*.yaml`
  mit Auto-Detection ueber V4L2-Control `sensor_name`. Erstes Live-Profil:
  `OV9281.yaml` (verifiziert auf `UniversitySidney1`).
- **Sensor-Katalog** (`vc_trigger.sensor_catalog_loader`): 25
  vorregistrierte VC-MIPI-Sensor-Metadaten unter
  `src/vc_trigger/sensor_profiles/catalog/*.yaml` — 2 OmniVision (OV7251,
  OV9281) und 23 Sony (IMX178, IMX183, IMX226, IMX250, IMX252, IMX264,
  IMX265, IMX273, IMX290, IMX296, IMX297, IMX327, IMX335, IMX392, IMX412,
  IMX415, IMX462, IMX565, IMX566, IMX567, IMX568, IMX585, IMX900). Loader-API:
  `available_catalog_entries()`, `load_catalog_entry()`,
  `resolve_by_module_id()`.
- **3-Wege-Sensor-Detection-Cascade** im Sensor-Test-Tab
  (`discover_sensor()`): Zustand `live` (Registry-YAML gefunden, Teal-Label
  `#01696F`), `catalog` (nur Katalog-Metadaten, Warm-Orange-Banner `#964219`),
  `unknown` (weder Registry noch Katalog, Magenta-Fehlerbanner `#A12C7B`).
  Semantische Farben aus der NOTAVIS-Nexus-Designpalette.

### Fixed

- **Qt-Offscreen-Test-Stabilitaet** (`tests/test_desktop_ui_catalog.py`):
  Widget-Sichtbarkeit wird ueber `isHidden()` statt `isVisible()` geprueft.
  `isVisible()` liefert unter `QT_QPA_PLATFORM=offscreen` `False`, solange kein
  `show()` mit vollstaendiger Parent-Kette lief; `isHidden()` reflektiert den
  Widget-lokalen State und ist der korrekte Check in Fixtures ohne
  Event-Loop.

### Documentation

- **README:** dokumentiert die 3-Wege-Sensor-Detection-Cascade mit exakten
  Textausgaben und Farbcodes sowie den 25-Sensor-Katalog (Zweck,
  Vendor-Liste, Programmzugriff, Ergaenzungs-Workflow, Upgrade-zu-Live-Profil-
  Pfad). Roadmap auf den Stand nach PR #13 gebracht.

### Verified

- **Live-Verifikation auf `UniversitySidney1`** (Raspberry Pi CM5, Kernel
  6.18.34+rpt-rpi-2712, Python 3.13.5): 135/135 Tests gruen
  (`QT_QPA_PLATFORM=offscreen VC_TRIGGER_MOCK=1 pytest -q`), OV9281 live auf
  `/dev/v4l-subdev2` erkannt, Cascade schaltet auf Zustand `live` mit
  `OmniVision OV9281 (VC MIPI)` als Live-Profil und
  `OV9281 (VC MIPI, global shutter, mono)` als Katalog-Eintrag.

[Unreleased]: https://github.com/Notavis-GmbH/notavis-mipi-trigger/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Notavis-GmbH/notavis-mipi-trigger/releases/tag/v0.1.0
