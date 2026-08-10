# notavis-mipi-trigger-public

Externer **GPIO/PWM-Trigger** fuer Vision-Components-MIPI-Kameras. Zielplattform:
Raspberry Pi Compute Module 5 (Debian 13 Trixie, aarch64). Zwei gleichwertige
Frontends teilen sich denselben `TriggerController`:

- **Streamlit-Web-UI** — Browser-basiert, remote nutzbar unter `http://<board>:8501`
- **PySide6-Desktop-UI** — native Qt-App, laeuft direkt auf dem CM5 (HDMI / DSI
  am Board)

Beide UIs erzeugen identische Signale auf GPIO 18.

Dies ist die **oeffentliche Auslieferungs-Linie** des internen NOTAVIS-Trigger-Tools.
Sie enthaelt ausschliesslich stabile, freigegebene Releases fuer den Einsatz auf
Kunden-Boards und in externen Integrationen.

## Ein-Zeilen-Installation (empfohlen)

Auf einem frisch geflashten Raspberry Pi CM5 mit Debian 13 Trixie:

```bash
curl -fsSL https://github.com/Notavis-GmbH/notavis-mipi-trigger-public/releases/download/v0.1.1/install.sh | sudo bash
```

Das Skript:

1. installiert alle APT-Pakete (`swig`, `liblgpio-dev`, `python3-lgpio`, `python3-venv`, `python3-pip`, `build-essential`)
2. prueft `gpio`-Gruppenmitgliedschaft des Standard-Users
3. laedt den signierten Release-Tarball von GitHub
4. verifiziert die SHA256-Pruefsumme
5. sichert eine ggf. vorhandene Vorinstallation
6. entpackt nach `/home/raspberrypi/vc-trigger`
7. erzeugt ein Python-virtualenv und installiert alle Runtime-Deps
8. richtet den systemd-Service `vc-trigger.service` ein und startet ihn

Nach dem Lauf ist die Web-UI unter `http://<board-ip>:8501` erreichbar.

## Ziel

Steuerung des Kamera-Triggers ueber GPIO 18 (Hardware-PWM) mit zwei Modi:

- **Einzel-Puls (Single-Shot):** definierte Pulsdauer in Millisekunden, manuell
  ausgeloest
- **Kontinuierliches PWM-Signal:** Frequenz (1-200 Hz) und Duty Cycle (0-100 %),
  zur Laufzeit einstellbar

Alle Parameter sind ueber das UI im laufenden Betrieb aenderbar, ohne dass die
Applikation neu gestartet wird.

## Zielhardware

| Komponente | Wert |
|---|---|
| Board | Raspberry Pi Compute Module 5 rev 1.0 (4 GB) |
| OS | Debian 13 (Trixie), aarch64 |
| Python | 3.12 (System) |
| Trigger-Pin | GPIO 18 (Hardware-PWM Kanal 0) |
| GPIO-Backend | `gpiozero` mit `lgpio`-Pin-Factory |

## Board-Voraussetzungen (frischer CM5)

Der `install.sh`-Ein-Zeiler erledigt das automatisch. Bei manueller Installation:

```bash
sudo apt update
sudo apt install -y swig liblgpio-dev python3-lgpio python3-venv python3-pip build-essential
```

## Manuelle Installation (fuer Entwickler)

```bash
git clone https://github.com/Notavis-GmbH/notavis-mipi-trigger-public.git vc-trigger
cd vc-trigger
python3 -m venv .venv
.venv/bin/pip install --upgrade pip setuptools wheel
.venv/bin/pip install -e '.[dev,desktop]'
.venv/bin/python -m pytest -q
```

Details siehe [`deploy/DEPLOY.md`](deploy/DEPLOY.md).

## Nutzung

### Streamlit-Web-UI

```bash
.venv/bin/streamlit run src/vc_trigger/ui.py --server.address 0.0.0.0 --server.port 8501
```

Browser: `http://<board-ip>:8501`. DE/EN-Toggle in der Sidebar (Standard DE).

### PySide6-Desktop-UI

```bash
.venv/bin/vc-trigger-desktop
# oder
.venv/bin/python -m vc_trigger.desktop_ui
```

Erwartet ein Display (`$DISPLAY` bzw. Wayland). Fuer headless Tests:
`QT_QPA_PLATFORM=offscreen`.

### Mock-Modus (ohne Board)

```bash
VC_TRIGGER_MOCK=1 .venv/bin/vc-trigger-desktop
```

Nutzt einen In-Memory-GPIO-Backend, kein `/dev/gpiochip*`-Zugriff.

## Systemd-Service

Das Ein-Zeilen-Installer-Skript installiert den Service automatisch. Manueller
Start:

```bash
sudo systemctl start vc-trigger.service
sudo systemctl enable vc-trigger.service
systemctl status vc-trigger.service
journalctl -u vc-trigger.service -f
```

## Lizenz

MIT License — siehe [`LICENSE`](LICENSE). Copyright (c) 2026 NOTAVIS GmbH.

## Beitraege

Issues und Pull Requests sind willkommen. Fuer groessere Aenderungen bitte
vorher ein Issue oeffnen. Contributor sichern zu, dass ihr Beitrag unter der
MIT-Lizenz dieses Repos veroeffentlicht werden darf.

## Kontakt

- Business: [NOTAVIS GmbH](https://www.notavis.com), Frankfurt am Main
- Technisch: Patrik Drexel <patrik.drexel@notavis.com>
