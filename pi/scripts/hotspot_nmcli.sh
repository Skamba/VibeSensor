#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_PATH="${PI_DIR}/config.yaml"

eval "$(
python3 - "${CONFIG_PATH}" <<'PY'
import pathlib
import sys

defaults = {
    "ssid": "VibeSensor",
    "psk": "vibesensor123",
    "ip": "192.168.4.1/24",
    "channel": 7,
    "ifname": "wlan0",
    "con_name": "VibeSensor-AP",
}

config_path = pathlib.Path(sys.argv[1])
cfg = {}
if config_path.exists():
    try:
        import yaml
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            cfg = raw.get("ap", {}) or {}
    except Exception:
        cfg = {}

ap = {**defaults, **cfg}
for k, v in ap.items():
    print(f"{k.upper()}={v!r}")
PY
)"

if ! command -v nmcli >/dev/null 2>&1; then
  echo "nmcli not found. Install NetworkManager first."
  exit 1
fi

if ! dpkg -s dnsmasq >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y dnsmasq
fi

sudo python3 - <<'PY'
from configparser import ConfigParser
from pathlib import Path

path = Path("/etc/NetworkManager/NetworkManager.conf")
cfg = ConfigParser()
if path.exists():
    cfg.read(path)
if "main" not in cfg:
    cfg["main"] = {}
cfg["main"]["dns"] = "dnsmasq"
with path.open("w", encoding="utf-8") as fh:
    cfg.write(fh)
PY

sudo systemctl disable --now dnsmasq.service >/dev/null 2>&1 || true
sudo systemctl restart NetworkManager

if ! nmcli -t -f NAME connection show | grep -Fxq "${CON_NAME}"; then
  nmcli connection add type wifi ifname "${IFNAME}" con-name "${CON_NAME}" autoconnect yes ssid "${SSID}"
fi

nmcli connection modify "${CON_NAME}" \
  802-11-wireless.mode ap \
  802-11-wireless.band bg \
  802-11-wireless.channel "${CHANNEL}" \
  802-11-wireless-security.key-mgmt wpa-psk \
  802-11-wireless-security.psk "${PSK}" \
  ipv4.method shared \
  ipv4.addresses "${IP}" \
  ipv6.method ignore

nmcli connection up "${CON_NAME}"
nmcli -f GENERAL.STATE,IP4.ADDRESS connection show "${CON_NAME}"
