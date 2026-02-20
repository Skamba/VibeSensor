#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$(id -u)" -ne 0 ]; then
  if ! command -v sudo >/dev/null 2>&1; then
    echo "This script requires root (or sudo) to configure hotspot and write /var/log/wifi diagnostics."
    exit 1
  fi
  exec sudo -E bash "$0" "$@"
fi

run_as_root() {
  "$@"
}

LOG_DIR=/var/log/wifi
install -d -m 0755 "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/hotspot.log"

touch "${LOG_FILE}"

if [ -f "${LOG_FILE}" ]; then
  size_bytes=$(stat -c '%s' "${LOG_FILE}" 2>/dev/null || echo 0)
  if [ "${size_bytes}" -gt 5242880 ]; then
    mv -f "${LOG_FILE}" "${LOG_FILE}.1"
    : >"${LOG_FILE}"
  fi
fi

exec > >(awk '{ print strftime("%Y-%m-%dT%H:%M:%S%z"), $0 }' >>"${LOG_FILE}") 2>&1

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

dump_cmd() {
  local name="$1"
  shift
  local out_file="${LOG_DIR}/${name}.txt"
  echo "[dump] ${name}: $*"
  set +e
  "$@" >"${out_file}" 2>&1
  local rc=$?
  set -e
  echo "[dump] ${name}: rc=${rc} file=${out_file}"
  return 0
}

dump_all() {
  local phase="${1:-}"
  local prefix=""
  if [ -n "${phase}" ]; then
    prefix="${phase}_"
  fi

  dump_cmd "${prefix}meta" bash -c 'date -Is; uname -a'
  dump_cmd "${prefix}ip_link" ip link
  dump_cmd "${prefix}rfkill" rfkill list
  dump_cmd "${prefix}nm_general" nmcli general status
  dump_cmd "${prefix}nm_dev" nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status
  dump_cmd "${prefix}nm_conn_active" nmcli -t -f NAME,UUID,TYPE,DEVICE,STATE connection show --active
  dump_cmd "${prefix}nm_conn_all" nmcli connection show
  dump_cmd "${prefix}iw_dev" iw dev
  if [ -n "${IFNAME:-}" ]; then
    dump_cmd "${prefix}iw_info" iw dev "${IFNAME}" info
  fi
  dump_cmd "${prefix}dmesg_tail" bash -c 'dmesg | tail -n 250'
  dump_cmd "${prefix}sysctl_wifi" bash -c 'sysctl net.ipv4.ip_forward 2>/dev/null || true'
}

write_summary() {
  local status="$1"
  local rc="$2"
  local summary_file="${LOG_DIR}/summary.txt"
  local con_name="${CON_NAME:-VibeSensor-AP}"
  local ap_exists="no"
  local final_status="(unavailable)"

  if run_as_root nmcli connection show "${con_name}" >/dev/null 2>&1; then
    ap_exists="yes"
  fi

  final_status="$(run_as_root nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status 2>/dev/null || true)"

  cat >"${summary_file}" <<EOF
status=${status}
rc=${rc}
timestamp=$(date -Is)
configured_ifname=${CONFIGURED_IFNAME:-}
detected_ifname=${DETECTED_IFNAME:-}
effective_ifname=${IFNAME:-}
ssid=${SSID:-}
channel=${CHANNEL:-}
con_name=${CON_NAME:-}
ip=${IP:-}
ap_connection_exists=${ap_exists}

final_nmcli_device_status:
${final_status}
EOF
}

trap 'rc=$?; failed_line=${BASH_LINENO[0]:-0}; failed_cmd=${BASH_COMMAND:-unknown}; echo "ERROR rc=${rc} line=${failed_line} cmd=${failed_cmd}"; dump_all error; write_summary FAILED "${rc}"; exit "${rc}"' ERR
trap 'rc=$?; echo "EXIT rc=${rc}"' EXIT

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
    "psk": "",
    "ip": "10.4.0.1/24",
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

CONFIGURED_IFNAME="${IFNAME}"
DETECTED_IFNAME=""

interface_exists() {
  ip link show "$1" >/dev/null 2>&1
}

detect_wifi_ifname() {
  run_as_root nmcli -t -f DEVICE,TYPE device status 2>/dev/null | awk -F: '$2=="wifi"{print $1; exit}'
}

# Boot invariant:
# 1) bring up AP offline first (must succeed with no internet),
# 2) optional uplink update remains non-fatal and must never block AP startup.

dump_all pre

if ! command -v nmcli >/dev/null 2>&1; then
  echo "nmcli not found. Install NetworkManager first."
  exit 1
fi

if ! command -v dnsmasq >/dev/null 2>&1; then
  echo "WARNING: dnsmasq not found. Hotspot AP can still come up, but DHCP/DNS may not work."
fi

run_as_root rfkill unblock wifi >/dev/null 2>&1 || true
run_as_root nmcli radio wifi on >/dev/null 2>&1 || true

if ! interface_exists "${IFNAME}"; then
  DETECTED_IFNAME="$(detect_wifi_ifname || true)"
  if [ -n "${DETECTED_IFNAME}" ]; then
    echo "Configured IFNAME '${IFNAME}' not found; using detected wifi interface '${DETECTED_IFNAME}'"
    IFNAME="${DETECTED_IFNAME}"
  else
    echo "Configured IFNAME '${IFNAME}' not found and no wifi interface detected"
    write_summary FAILED 20
    exit 20
  fi
else
  DETECTED_IFNAME="${IFNAME}"
fi

for attempt in $(seq 1 20); do
  running_state="$(run_as_root nmcli -t -f RUNNING general 2>/dev/null || true)"
  echo "NetworkManager readiness attempt ${attempt}: running='${running_state}'"
  if echo "${running_state}" | grep -iq 'running'; then
    break
  fi
  if run_as_root nmcli general status >/dev/null 2>&1; then
    break
  fi
  if [ "${attempt}" -eq 20 ]; then
    echo "NetworkManager did not become ready within 20 attempts"
    dump_all nm_not_ready
    write_summary FAILED 21
    exit 21
  fi
  sleep 1
done

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
  ipv4.method shared \
  ipv4.addresses "${IP}" \
  ipv6.method ignore

if [ -n "${PSK}" ]; then
  run_as_root nmcli connection modify "${CON_NAME}" \
    802-11-wireless-security.key-mgmt wpa-psk \
    802-11-wireless-security.psk "${PSK}"
else
  run_as_root nmcli connection modify "${CON_NAME}" \
    802-11-wireless-security.key-mgmt none
fi

if ! run_as_root nmcli connection up "${CON_NAME}"; then
  echo "AP connection bring-up failed for ${CON_NAME}"
  dump_all ap_failed
  write_summary FAILED 22
  exit 22
fi

if ! maybe_update_from_uplink; then
  echo "WARNING: uplink update step failed; continuing with hotspot enabled."
fi

run_as_root nmcli connection up "${CON_NAME}" >/dev/null 2>&1 || true
run_as_root nmcli -f GENERAL.STATE,IP4.ADDRESS connection show "${CON_NAME}"
dump_all post
write_summary OK 0
