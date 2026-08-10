# notavis-mipi-trigger-public

Externer **GPIO/PWM-Kamera-Trigger** fuer den Raspberry Pi. Zielplattform:
Raspberry Pi Compute Module 5 (Debian 13 Trixie, aarch64) — laeuft auch auf
Raspberry Pi 5, Pi 4 und Pi Zero 2 W mit Debian 12 (Bookworm) oder neuer.

Zwei gleichwertige Frontends teilen sich denselben `TriggerController`:

- **Streamlit-Web-UI** — Browser-basiert, remote nutzbar unter `http://<board>:8501`
- **PySide6-Desktop-UI** — native Qt-App, laeuft direkt am HDMI-/DSI-Ausgang

Beide UIs erzeugen identische Signale auf **GPIO 18** (Hardware-PWM-fahiger Pin).
Es findet **keine** Kamera-Kommunikation statt — dieses Tool schaltet nur den
Trigger-Pin. Die Kamera muss die Trigger-Flanke selbst auswerten (z. B. VC MIPI
`trigger_mode=External`).

Dies ist die **oeffentliche Auslieferungs-Linie** des internen NOTAVIS-Trigger-Tools.
Sie enthaelt ausschliesslich stabile, freigegebene Releases fuer den Einsatz auf
Kunden-Boards und externen Integrationen.

## Ein-Zeilen-Installation (empfohlen)

Auf einem frisch geflashten Raspberry Pi (Debian 12/13) als Standard-User `pi`
oder aequivalent mit sudo-Rechten:

```bash
curl -fsSL https://raw.githubusercontent.com/Notavis-GmbH/notavis-mipi-trigger-public/main/install/install.sh | sudo bash
```

Nach dem Durchlauf:

- systemd-Service `vc-trigger.service` laeuft und ist enabled
- Web-UI erreichbar unter `http://<board-ip>:8501`
- Desktop-UI via `vc-trigger-desktop` (falls X11/Wayland verfuegbar)

## Funktionsumfang

| Modus | Beschreibung |
|---|---|
| **Single-Shot** | Ein einzelner Rechteck-Puls definierter Dauer (0.1 – 1000 ms) |
| **PWM** | Kontinuierliches Signal (1 – 200 Hz, Duty 0 – 100 %) |

Sicherheits-Garantien im Controller:

- Jeder Modus-Wechsel stoppt das laufende Signal sauber.
- Beim Beenden der UI wird der Pin auf LOW gezogen (kein „haengender" Trigger).
- Parallele Single-Shots werden serialisiert (kein Doppel-Trigger).
- Alle Aktionen brauchen einen expliziten Button-Klick. Slider-Aenderungen
  schalten nichts.

## Manuelle Installation

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv git
git clone https://github.com/Notavis-GmbH/notavis-mipi-trigger-public.git
cd notavis-mipi-trigger-public
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[desktop]'

# Web-UI starten (Port 8501, alle Interfaces)
streamlit run src/vc_trigger/ui.py --server.address 0.0.0.0 --server.port 8501

# oder Desktop-UI
vc-trigger-desktop
```

## Entwicklung ohne Board (Mock-Modus)

Auf einem Entwicklungs-PC ohne GPIO-Hardware:

```bash
export VC_TRIGGER_MOCK=1
export QT_QPA_PLATFORM=offscreen   # nur fuer headless Test-Runs
pytest -q
```

## Anforderungen

- **Hardware:** Raspberry Pi mit GPIO-Header, GPIO 18 als Ausgang frei
- **OS:** Debian 12 Bookworm oder Debian 13 Trixie (aarch64)
- **Python:** 3.12 oder 3.13
- **Bibliotheken:** `gpiozero`, `lgpio` (auf Debian via `apt install python3-lgpio`)

## Lizenz

MIT — siehe [LICENSE](LICENSE).

## Kontakt

NOTAVIS GmbH, Frankfurt am Main
`patrik.drexel@notavis.com`
