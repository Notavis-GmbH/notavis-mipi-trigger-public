# Docker-Betrieb (optional)

Dieses Dokument beschreibt den Container-Betrieb der **Streamlit-Web-UI** von
notavis-mipi-trigger. Es ist eine Alternative zu `deploy/DEPLOY.md`
(systemd-Service, native venv-Installation) — beide Wege bedienen dieselbe
`TriggerController`-Logik.

> **Scope.** Der Container enthaelt ausschliesslich die Web-UI. Die
> PySide6-Desktop-UI (`vc-trigger-desktop`) laeuft nativ am HDMI-/DSI-Ausgang
> des Boards und wird bewusst nicht containerisiert — dafuer waere
> X11-/Wayland-Socket-Passthrough noetig, was auf einem Pi mit direkt
> angeschlossenem Display unnoetige Komplexitaet und Fehlerquellen einbringt.

> **Empfehlung.** Fuer den **produktiven** Einsatz auf einem Kunden-Board
> bleibt der systemd-Service aus `deploy/DEPLOY.md` der einfachere und
> robustere Weg (keine Docker-Laufzeit auf dem Board noetig, direkter
> GPIO-Zugriff ueber die `gpio`-Gruppe). Docker eignet sich vor allem fuer:
> - Entwicklung/Testing auf einem PC ohne Pi-Hardware (Mock-Modus),
> - Umgebungen, in denen ohnehin schon Container-Orchestrierung laeuft,
> - reproduzierbare CI-Builds.

## 1. Image bauen

### Single-Arch (lokal, fuer die aktuelle Plattform)

```bash
docker build -t notavis-mipi-trigger:local .
```

### Multi-Arch (amd64 + arm64) mit `buildx`

`lgpio` besitzt keine vorgefertigten Wheels (siehe Kommentar im
`Dockerfile`) und wird bei jedem Build aus dem Quellcode uebersetzt (SWIG +
C). Das funktioniert unter QEMU-Emulation, dauert dort aber je nach
Host-CPU spuerbar laenger als ein natives `arm64`-Build.

```bash
# Einmalig: Buildx-Builder mit QEMU-Unterstuetzung anlegen
docker buildx create --use --name notavis-builder
docker run --privileged --rm tonistiigi/binfmt --install all   # QEMU-Handler registrieren

# Build + Push in ein Registry (z. B. GHCR) in einem Schritt
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t ghcr.io/notavis-gmbh/notavis-mipi-trigger:0.1.2 \
  -t ghcr.io/notavis-gmbh/notavis-mipi-trigger:latest \
  --push .
```

`--push` ist bei Multi-Arch-Builds noetig, weil `docker buildx --load` pro
Aufruf nur eine einzelne Plattform in den lokalen Docker-Daemon laden kann.
Ohne Registry-Push koennen die beiden Architekturen einzeln lokal geladen
und getestet werden:

```bash
docker buildx build --platform linux/amd64 -t notavis-mipi-trigger:amd64 --load .
docker buildx build --platform linux/arm64 -t notavis-mipi-trigger:arm64 --load .
```

## 2. Betrieb im Mock-Modus (kein Board noetig)

Fuer Entwicklung/UI-Tests auf einem Laptop ohne GPIO-Hardware:

```bash
docker compose up --build
```

Das mitgelieferte `docker-compose.yml` setzt standardmaessig
`VC_TRIGGER_MOCK=1` — jede Aktion in der UI wird simuliert
(`_MockDigitalOutput` / `_MockPwmOutput` in `src/vc_trigger/controller.py`),
es findet kein echter Hardwarezugriff statt. Die UI ist danach unter
`http://localhost:8501` erreichbar.

## 3. Betrieb auf echter Pi-Hardware (GPIO-Passthrough)

Fuer echten Trigger-Betrieb muss der Container Zugriff auf das
`gpiochip`-Character-Device des Boards erhalten. Zwei Dinge vorher pruefen:

### 3.1 Richtiges gpiochip-Device ermitteln

Die RP1-Chip-Nummerierung auf Pi 5 / CM5 hat sich zwischen Kernel-Versionen
geaendert:

| Board / Kernel | Device |
|---|---|
| CM5/Pi 5, Kernel < 6.6.45 | `/dev/gpiochip4` |
| CM5/Pi 5, Kernel >= 6.6.45 | `/dev/gpiochip0` |
| Aeltere Pi-Modelle (3B, 4B, Zero 2 W) | `/dev/gpiochip0` |

Auf dem Zielboard verifizieren statt zu raten:

```bash
ls -l /dev/gpiochip*
uname -r
gpiodetect   # falls libgpiod-Tools installiert sind; zeigt Label z. B. "pinctrl-rp1"
```

### 3.2 GID der `gpio`-Gruppe ermitteln

```bash
getent group gpio
# z. B. gpio:x:997:raspberrypi
```

### 3.3 `docker-compose.yml` anpassen

In der mitgelieferten `docker-compose.yml` den auskommentierten Block
aktivieren und mit den Werten aus 3.1/3.2 fuellen:

```yaml
    environment:
      VC_TRIGGER_MOCK: "0"   # echten Hardwarezugriff aktivieren
    devices:
      - /dev/gpiochip0:/dev/gpiochip0
    group_add:
      - "997"   # GID aus `getent group gpio`
```

Danach:

```bash
docker compose up -d --build
docker compose logs -f
```

Erwartung im Log: `TriggerController ready on GPIO 18 (mock=False)` (aus
`src/vc_trigger/controller.py`).

### 3.4 Troubleshooting

| Symptom | Wahrscheinliche Ursache | Naechster Schritt |
|---|---|---|
| `GPIO nicht verfuegbar: ...` in der UI | Falsches `gpiochip*`-Device gemappt | `ls -l /dev/gpiochip*` auf dem Host erneut pruefen, `devices:` korrigieren |
| `Permission denied` beim Oeffnen des Devices | Container-Prozess nicht in der `gpio`-Gruppe | GID in `group_add:` gegen `getent group gpio` auf dem **Host** pruefen |
| Alles startet, aber der Pin bewegt sich nicht | `VC_TRIGGER_MOCK=1` noch aktiv | Environment-Variable auf `"0"` setzen und Container neu starten |

Als letzte Eskalationsstufe (nur zum Debuggen, nicht fuer den Dauerbetrieb
empfohlen) kann der Container mit `privileged: true` statt gezieltem
Device-Mapping gestartet werden — das raeumt jedoch mehr Rechte ein als
noetig und sollte nach erfolgreicher Fehlersuche wieder zurueckgebaut werden.

## 4. Healthcheck

Das Image definiert einen `HEALTHCHECK` gegen den Streamlit-internen
Endpoint `/_stcore/health`. Status pruefen:

```bash
docker inspect --format='{{json .State.Health}}' vc-trigger | python3 -m json.tool
```

## 5. Aufraeumen

```bash
docker compose down
docker image rm notavis-mipi-trigger:latest
```
