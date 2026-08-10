#!/usr/bin/env bash
# install.sh — notavis-mipi-trigger-public
#
# Ein-Zeilen-Installer:
#   curl -fsSL https://raw.githubusercontent.com/Notavis-GmbH/notavis-mipi-trigger-public/main/install/install.sh | sudo bash
#
# Zielsystem: Raspberry Pi CM5 / Pi 5 / Pi 4, Debian 12 (Bookworm) oder
#             Debian 13 (Trixie), aarch64.
# Standardbenutzer wird per RUN_USER-Env angepasst (Default: raspberrypi).
#
# Idempotent: bestehende Installation wird gesichert, nicht ungefragt ueberschrieben.

set -euo pipefail

# --- Konfiguration ----------------------------------------------------------
VERSION="${VERSION:-v0.1.2}"
REPO="Notavis-GmbH/notavis-mipi-trigger-public"
BASE_URL="https://raw.githubusercontent.com/${REPO}/main/install"
TARBALL_NAME="notavis-mipi-trigger-${VERSION}.tar.gz"
TARBALL_URL="${BASE_URL}/${TARBALL_NAME}"
SHA256_URL="${BASE_URL}/${TARBALL_NAME}.sha256"
UNPACK_ROOT="notavis-mipi-trigger-${VERSION}"

RUN_USER="${RUN_USER:-raspberrypi}"
RUN_GROUP="${RUN_GROUP:-${RUN_USER}}"
INSTALL_DIR="${INSTALL_DIR:-/home/${RUN_USER}/vc-trigger}"
VENV_DIR="${INSTALL_DIR}/.venv"

SERVICE_SRC="${INSTALL_DIR}/deploy/vc-trigger.service"
SERVICE_DST="/etc/systemd/system/vc-trigger.service"

# --- Pre-flight -------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
  echo "ERROR: dieses Skript braucht root (sudo)." >&2
  exit 1
fi

if ! id -u "${RUN_USER}" >/dev/null 2>&1; then
  echo "ERROR: Ziel-User '${RUN_USER}' existiert nicht." >&2
  echo "       Setze RUN_USER=<user> und starte neu, z. B.:" >&2
  echo "       curl -fsSL ${BASE_URL}/install.sh | sudo RUN_USER=meinuser bash" >&2
  exit 1
fi

# --- APT-Prerequisites ------------------------------------------------------
echo "[1/8] Pruefe APT-Voraussetzungen ..."
MISSING=()
for pkg in swig liblgpio-dev python3-lgpio python3-venv python3-pip build-essential curl ca-certificates; do
  if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
    MISSING+=("$pkg")
  fi
done
if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "      installiere: ${MISSING[*]}"
  apt-get update
  apt-get install -y "${MISSING[@]}"
else
  echo "      alle APT-Pakete vorhanden."
fi

# --- gpio-Gruppe pruefen ----------------------------------------------------
echo "[2/8] Pruefe gpio-Gruppenmitgliedschaft fuer ${RUN_USER} ..."
if ! id -nG "${RUN_USER}" | tr ' ' '\n' | grep -qx "gpio"; then
  echo "      fuege ${RUN_USER} zur Gruppe gpio hinzu ..."
  usermod -aG gpio "${RUN_USER}"
  echo "      WARNUNG: ${RUN_USER} muss sich neu einloggen damit die Gruppe greift."
else
  echo "      ${RUN_USER} ist in Gruppe gpio."
fi

# --- Tarball laden ----------------------------------------------------------
echo "[3/8] Lade Release-Tarball von GitHub ..."
TMPDIR=$(mktemp -d)
trap 'rm -rf "${TMPDIR}"' EXIT

curl -fsSL "${TARBALL_URL}"  -o "${TMPDIR}/${TARBALL_NAME}"
curl -fsSL "${SHA256_URL}"   -o "${TMPDIR}/${TARBALL_NAME}.sha256"

echo "[4/8] Verifiziere SHA256 ..."
cd "${TMPDIR}"
if ! sha256sum -c "${TARBALL_NAME}.sha256"; then
  echo "ERROR: SHA256-Verifikation fehlgeschlagen. Abbruch." >&2
  exit 1
fi
cd - >/dev/null

# --- Backup bestehende Installation -----------------------------------------
if [[ -d "${INSTALL_DIR}" ]]; then
  BACKUP="${INSTALL_DIR}.backup-$(date +%Y%m%d-%H%M%S)"
  echo "[5/8] Sichere bestehende Installation nach ${BACKUP} ..."
  if systemctl is-active --quiet vc-trigger.service 2>/dev/null; then
    echo "      stoppe laufenden vc-trigger.service ..."
    systemctl stop vc-trigger.service
  fi
  mv "${INSTALL_DIR}" "${BACKUP}"
else
  echo "[5/8] Keine vorherige Installation gefunden - frisch."
fi

# --- Entpacken --------------------------------------------------------------
echo "[6/8] Entpacke Tarball nach ${INSTALL_DIR} ..."
tar xzf "${TMPDIR}/${TARBALL_NAME}" -C "${TMPDIR}"
if [[ ! -d "${TMPDIR}/${UNPACK_ROOT}" ]]; then
  echo "ERROR: Tarball-Struktur unerwartet (fehlender Root ${UNPACK_ROOT})." >&2
  exit 1
fi
mv "${TMPDIR}/${UNPACK_ROOT}" "${INSTALL_DIR}"
chown -R "${RUN_USER}:${RUN_GROUP}" "${INSTALL_DIR}"

# --- Virtualenv + Runtime-Deps ----------------------------------------------
echo "[7/8] Erzeuge virtualenv + installiere Runtime-Deps ..."
sudo -u "${RUN_USER}" python3 -m venv "${VENV_DIR}"
sudo -u "${RUN_USER}" "${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel
sudo -u "${RUN_USER}" "${VENV_DIR}/bin/pip" install "${INSTALL_DIR}"

echo "      verifiziere ..."
sudo -u "${RUN_USER}" VC_TRIGGER_MOCK=1 "${VENV_DIR}/bin/python" -c "
import vc_trigger
from vc_trigger.controller import get_controller
from vc_trigger.models import TriggerMode
c = get_controller(mock=True)
assert c.mode == TriggerMode.IDLE
print(f'  vc_trigger:  {vc_trigger.__file__}')
print(f'  Streamlit:   {__import__(\"streamlit\").__version__}')
print(f'  Starlette:   {__import__(\"starlette\").__version__}')
"

# --- Systemd-Service --------------------------------------------------------
echo "[8/8] Installiere systemd-Unit ..."
# Wenn RUN_USER != raspberrypi, patchen wir die Unit
if [[ "${RUN_USER}" != "raspberrypi" ]]; then
  sed -i "s|/home/raspberrypi/vc-trigger|${INSTALL_DIR}|g" "${SERVICE_SRC}"
  sed -i "s|^User=raspberrypi|User=${RUN_USER}|" "${SERVICE_SRC}"
  sed -i "s|^Group=raspberrypi|Group=${RUN_GROUP}|" "${SERVICE_SRC}"
fi
cp "${SERVICE_SRC}" "${SERVICE_DST}"
systemctl daemon-reload
systemctl enable vc-trigger.service
systemctl restart vc-trigger.service
sleep 3
if systemctl is-active --quiet vc-trigger.service; then
  echo "      vc-trigger.service ist active."
else
  echo "      WARNUNG: Service nicht active - siehe:" >&2
  echo "               journalctl -u vc-trigger.service -n 30" >&2
fi

# --- Abschluss --------------------------------------------------------------
IP=$(hostname -I | awk '{print $1}')
cat <<EOF

==========================================
  Installation abgeschlossen.
==========================================

Version:    ${VERSION}
Zielpfad:   ${INSTALL_DIR}
User:       ${RUN_USER}
Web-UI:     http://${IP:-<board-ip>}:8501

Status:     systemctl status vc-trigger.service
Logs:       journalctl -u vc-trigger.service -f

Docs:       https://github.com/${REPO}
Issues:     https://github.com/${REPO}/issues

EOF
