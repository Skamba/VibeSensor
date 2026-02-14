#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVICE_TEMPLATE="${PI_DIR}/systemd/vibesenser.service"
SERVICE_USER="${SUDO_USER:-$(id -un)}"
VENV_DIR="${PI_DIR}/.venv"

sudo apt-get update
sudo apt-get install -y \
  python3 \
  python3-venv \
  python3-pip \
  network-manager \
  dnsmasq \
  gpsd \
  gpsd-clients

python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -e "${PI_DIR}"

sudo install -d /etc/vibesenser
if [ ! -f /etc/vibesenser/config.yaml ]; then
  sudo cp "${PI_DIR}/config.example.yaml" /etc/vibesenser/config.yaml
fi

sed \
  -e "s#__PI_DIR__#${PI_DIR}#g" \
  -e "s#__VENV_DIR__#${VENV_DIR}#g" \
  -e "s#__SERVICE_USER__#${SERVICE_USER}#g" \
  "${SERVICE_TEMPLATE}" | sudo tee /etc/systemd/system/vibesenser.service >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable --now vibesenser.service
sudo systemctl status vibesenser.service --no-pager
