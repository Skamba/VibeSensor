#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="${VIBESENSOR_CONFIG_PATH:-/etc/vibesensor/config.yaml}"
SECRETS_PATH="${VIBESENSOR_WIFI_SECRETS_PATH:-/etc/vibesensor/wifi-secrets.env}"
REPO_PATH="${VIBESENSOR_REPO_PATH:-/opt/VibeSensor}"
GIT_REMOTE_URL="${VIBESENSOR_GIT_REMOTE:-https://github.com/Skamba/VibeSensor.git}"
GIT_BRANCH="${VIBESENSOR_GIT_BRANCH:-main}"
UPLINK_SCAN_TIMEOUT_SECONDS="${UPLINK_SCAN_TIMEOUT_SECONDS:-10}"
UPLINK_CONNECTION_NAME="${UPLINK_CONNECTION_NAME:-VibeSensor-Uplink}"
GIT_UPDATE_TIMEOUT_SECONDS="${GIT_UPDATE_TIMEOUT_SECONDS:-120}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --config"
        exit 1
      fi
      CONFIG_PATH="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: $0 [--config /path/to/config.yaml]"
      exit 1
      ;;
  esac
done

if [ "$(id -u)" -eq 0 ]; then
  AS_ROOT=""
else
  AS_ROOT="sudo"
fi

run_as_root() {
  if [ -n "${AS_ROOT}" ]; then
    sudo "$@"
  else
    "$@"
  fi
}

safe_source_secrets() {
  if [ ! -f "${SECRETS_PATH}" ]; then
    return 0
  fi

  local perms
  perms="$(run_as_root stat -c '%a' "${SECRETS_PATH}" 2>/dev/null || echo '')"
  if [ -n "${perms}" ] && [ "${perms}" != "600" ]; then
    echo "Warning: ${SECRETS_PATH} should use mode 600."
  fi

  # shellcheck disable=SC1090
  source "${SECRETS_PATH}"
}

maybe_update_from_uplink() {
  safe_source_secrets
  if [ -z "${WIFI_UPLINK_SSID:-}" ] || [ -z "${WIFI_UPLINK_PSK:-}" ]; then
    echo "No uplink Wi-Fi secrets configured; skipping update step."
    return 0
  fi

  local deadline
  deadline=$((SECONDS + UPLINK_SCAN_TIMEOUT_SECONDS))
  local found=0
  while [ "${SECONDS}" -lt "${deadline}" ]; do
    if run_as_root nmcli -t -f SSID dev wifi list ifname "${IFNAME}" --rescan yes | grep -Fxq "${WIFI_UPLINK_SSID}"; then
      found=1
      break
    fi
    sleep 1
  done

  if [ "${found}" -ne 1 ]; then
    echo "Uplink SSID '${WIFI_UPLINK_SSID}' not found within ${UPLINK_SCAN_TIMEOUT_SECONDS}s; continuing with hotspot."
    return 0
  fi

  echo "Found uplink SSID; attempting temporary connection for update."
  run_as_root nmcli connection delete "${UPLINK_CONNECTION_NAME}" >/dev/null 2>&1 || true
  run_as_root nmcli connection add type wifi ifname "${IFNAME}" con-name "${UPLINK_CONNECTION_NAME}" autoconnect no ssid "${WIFI_UPLINK_SSID}" >/dev/null
  run_as_root nmcli connection modify "${UPLINK_CONNECTION_NAME}" \
    802-11-wireless-security.key-mgmt wpa-psk \
    802-11-wireless-security.psk "${WIFI_UPLINK_PSK}" \
    ipv4.method auto \
    ipv6.method ignore

  if ! run_as_root nmcli connection up "${UPLINK_CONNECTION_NAME}" --wait 10 >/dev/null 2>&1; then
    echo "Uplink connection failed; continuing with hotspot."
    run_as_root nmcli connection delete "${UPLINK_CONNECTION_NAME}" >/dev/null 2>&1 || true
    return 0
  fi

  if [ -d "${REPO_PATH}/.git" ] && command -v git >/dev/null 2>&1; then
    echo "Updating ${REPO_PATH} from ${GIT_REMOTE_URL} (${GIT_BRANCH})..."
    # Keep the uplink active until git operations complete.
    if command -v timeout >/dev/null 2>&1; then
      run_as_root timeout "${GIT_UPDATE_TIMEOUT_SECONDS}" \
        git -C "${REPO_PATH}" remote set-url origin "${GIT_REMOTE_URL}" >/dev/null 2>&1 || true
      run_as_root timeout "${GIT_UPDATE_TIMEOUT_SECONDS}" \
        git -C "${REPO_PATH}" fetch --depth 1 origin "${GIT_BRANCH}" >/dev/null 2>&1 || true
      run_as_root timeout "${GIT_UPDATE_TIMEOUT_SECONDS}" \
        git -C "${REPO_PATH}" checkout "${GIT_BRANCH}" >/dev/null 2>&1 || true
      run_as_root timeout "${GIT_UPDATE_TIMEOUT_SECONDS}" \
        git -C "${REPO_PATH}" pull --ff-only origin "${GIT_BRANCH}" >/dev/null 2>&1 || true
    else
      run_as_root git -C "${REPO_PATH}" remote set-url origin "${GIT_REMOTE_URL}" >/dev/null 2>&1 || true
      run_as_root git -C "${REPO_PATH}" fetch --depth 1 origin "${GIT_BRANCH}" >/dev/null 2>&1 || true
      run_as_root git -C "${REPO_PATH}" checkout "${GIT_BRANCH}" >/dev/null 2>&1 || true
      run_as_root git -C "${REPO_PATH}" pull --ff-only origin "${GIT_BRANCH}" >/dev/null 2>&1 || true
    fi
  else
    echo "Repo path ${REPO_PATH} is not a git checkout; skipping update."
  fi

  run_as_root nmcli connection down "${UPLINK_CONNECTION_NAME}" >/dev/null 2>&1 || true
  run_as_root nmcli connection delete "${UPLINK_CONNECTION_NAME}" >/dev/null 2>&1 || true
}

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

if ! command -v dnsmasq >/dev/null 2>&1; then
  echo "WARNING: dnsmasq not found. Hotspot AP can still come up, but DHCP/DNS may not work."
fi

run_as_root install -d /etc/NetworkManager/conf.d
run_as_root tee /etc/NetworkManager/conf.d/99-vibesensor-dnsmasq.conf >/dev/null <<'EOF'
[main]
dns=dnsmasq
EOF

run_as_root systemctl disable --now dnsmasq.service >/dev/null 2>&1 || true
if ! run_as_root nmcli general reload >/dev/null 2>&1; then
  if ! run_as_root systemctl reload NetworkManager >/dev/null 2>&1; then
    run_as_root systemctl restart NetworkManager
  fi
fi

if ! run_as_root nmcli -t -f NAME connection show | grep -Fxq "${CON_NAME}"; then
  run_as_root nmcli connection add type wifi ifname "${IFNAME}" con-name "${CON_NAME}" autoconnect yes ssid "${SSID}"
fi

run_as_root nmcli connection modify "${CON_NAME}" \
  802-11-wireless.mode ap \
  802-11-wireless.band bg \
  802-11-wireless.channel "${CHANNEL}" \
  802-11-wireless-security.key-mgmt wpa-psk \
  802-11-wireless-security.psk "${PSK}" \
  ipv4.method shared \
  ipv4.addresses "${IP}" \
  ipv6.method ignore

run_as_root nmcli connection up "${CON_NAME}"

if ! maybe_update_from_uplink; then
  echo "WARNING: uplink update step failed; continuing with hotspot enabled."
fi

run_as_root nmcli connection up "${CON_NAME}" >/dev/null 2>&1 || true
run_as_root nmcli -f GENERAL.STATE,IP4.ADDRESS connection show "${CON_NAME}"
