# Deployment auf dem Raspberry Pi CM5

Zielsystem: **Raspberry Pi CM5**, Debian 13 (Trixie), aarch64, User
`raspberrypi` gemaess Notavis-Dev-Board-Baseline
(`notavis-dev-board-access`). Voraussetzung: der User `raspberrypi` ist
Mitglied der Gruppe `gpio` (Trixie-Standard auf Pi-Systemen).

> **Hinweis zur User-Konvention.** Frueher hat dieses Repo einen separaten
> User `notavis` erwartet. Auf Notavis-Dev-Boards ist der Standard-User
> aber `raspberrypi` (siehe Space-Project-Skill `notavis-dev-board-access`).
> Diese Anleitung folgt der Baseline; wer einen abweichenden User nutzt,
> passt Pfade und `User=`/`Group=` in `deploy/vc-trigger.service`
> entsprechend an.

## 1. Repo auschecken

```bash
cd /home/raspberrypi
git clone https://github.com/Notavis-GmbH/notavis-mipi-trigger.git vc-trigger
cd /home/raspberrypi/vc-trigger
```

## 2. Virtualenv und Abhaengigkeiten installieren

Auf Trixie ist das System-Python durch PEP 668 geschuetzt. Der empfohlene
Weg ist ein dediziertes venv unter `/home/raspberrypi/vc-trigger/.venv`.
**Wichtig:** `--system-site-packages` NICHT verwenden — das System-`protobuf`
kollidiert mit Streamlit und fuehrt beim Import zu
`ModuleNotFoundError: No module named 'google.protobuf.descriptor'`.

```bash
sudo apt-get install -y python3-venv
python3 -m venv .venv               # ohne --system-site-packages
.venv/bin/pip install --upgrade pip wheel setuptools
.venv/bin/pip install -e '.[dev]'
```

Verifikation:

```bash
.venv/bin/python -c "import vc_trigger; print(vc_trigger.__file__)"
# erwartet: /home/raspberrypi/vc-trigger/src/vc_trigger/__init__.py

.venv/bin/pip show starlette | grep Version
# erwartet: 0.47.x   (siehe Constraint in pyproject.toml)
```

## 3. GPIO-Backend pruefen

Die App verwendet `gpiozero` mit der `lgpio`-Pin-Factory (Trixie-Standard).
Sanity-Check ohne Board:

```bash
VC_TRIGGER_MOCK=1 .venv/bin/python -c \
    "from vc_trigger.controller import get_controller; c = get_controller(mock=True); print(c.mode)"
```

Erwartet: `TriggerMode.IDLE`.

## 4. Tests laufen lassen (Mock, kein Board noetig)

```bash
.venv/bin/python -m pytest -q
```

Erwartet: alle Tests gruen. Die Desktop-UI-Tests werden automatisch
uebersprungen, wenn das `desktop`-Extra (PySide6) nicht installiert ist.

## 5. Systemd-Service einrichten

```bash
sudo cp deploy/vc-trigger.service /etc/systemd/system/vc-trigger.service
sudo systemctl daemon-reload
sudo systemctl enable --now vc-trigger.service
sudo systemctl status vc-trigger.service --no-pager
```

Erwartet: `active (running)`. Die Unit ruft `.venv/bin/python -m streamlit`
auf; sie erwartet also, dass Schritt 2 ausgefuehrt wurde.

## 6. UI vom Laptop aufrufen

Im Browser auf dem Entwicklungsrechner:

```
http://<board-ip>:8501
```

Fuer das Dev-Board `UniversitySidney1` derzeit ueber ngrok erreichbar; ein
HTTP-Tunnel muss separat eingerichtet werden, falls die UI von ausserhalb des
LAN benoetigt wird (ist derzeit **nicht** Bestandteil dieses Repos).

## 7. Hardware-Verifikation (LED-Test)

Vor Anschluss an eine echte Kamera: LED + 330-Ohm-Widerstand zwischen GPIO 18
und GND stecken. Im UI:

1. Modus „Einzel-Puls", Pulsdauer 500 ms, „Trigger manuell ausloesen" —
   LED blitzt einmal auf.
2. Modus „PWM", Frequenz 5 Hz, Duty 50 %, „PWM starten" — LED blinkt
   sichtbar 5x pro Sekunde.
3. „PWM stoppen" — LED aus.

## Deinstallation

```bash
sudo systemctl disable --now vc-trigger.service
sudo rm /etc/systemd/system/vc-trigger.service
sudo systemctl daemon-reload
rm -rf /home/raspberrypi/vc-trigger
```
