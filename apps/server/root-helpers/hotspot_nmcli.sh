#!/usr/bin/env bash
# Provision the VibeSensor hotspot (vibesensor-hotspot.service runs this as root).
# It runs from the root-owned helper directory /usr/local/lib/vibesensor
# (install_systemd_units.sh) and must never run code from the service user's
# tree: settings come from vibesensor_hotspot.py next to it, under the system
# python3 -I.
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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
  local rc=0
  echo "[dump] ${name}: $*"
  # Diagnostics are best-effort; collection failures should not mask the main
  # error. "|| rc=$?" keeps a failing command from firing the ERR trap, which
  # "set +e" would not (NetworkManager still starting at boot fails
  # "nmcli general status" in the pre dump).
  "$@" >"${out_file}" 2>&1 || rc=$?
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

# shellcheck disable=SC2154  # Bash expands BASH_LINENO/BASH_COMMAND inside the ERR trap at runtime.
trap 'rc=$?; failed_line=${BASH_LINENO[0]:-0}; failed_cmd=${BASH_COMMAND:-unknown}; echo "ERROR rc=${rc} line=${failed_line} cmd=${failed_cmd}" >&2; dump_all error; write_summary FAILED "${rc}"; exit "${rc}"' ERR
trap 'rc=$?; echo "EXIT rc=${rc}"' EXIT

# vibesensor_hotspot.py shell-quotes every value it prints.
HOTSPOT_CONFIG_EXPORTS="$(/usr/bin/python3 -I "${SCRIPT_DIR}/vibesensor_hotspot.py" config "${CONFIG_PATH}")"
eval "${HOTSPOT_CONFIG_EXPORTS}"

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

# Captive portal: the AP's shared-mode dnsmasq (it serves only the hotspot
# interface) resolves the OS connectivity-probe hosts to the Pi, and the app
# redirects those probes to the UI, so phones open it automatically. The Pi's
# own resolver is untouched, so uplink updates still reach the real hosts.
run_as_root install -d /etc/NetworkManager/dnsmasq-shared.d
run_as_root tee /etc/NetworkManager/dnsmasq-shared.d/vibesensor-captive-portal.conf >/dev/null <<EOF
address=${CAPTIVE_DNS_ADDRESS}
EOF

run_as_root systemctl disable --now dnsmasq.service >/dev/null 2>&1 || true
if ! run_as_root nmcli general reload >/dev/null 2>&1; then
  if ! run_as_root systemctl reload NetworkManager >/dev/null 2>&1; then
    run_as_root systemctl restart NetworkManager
  fi
fi

# Always recreate the profile: it must not keep stale security fields
# (WEP/WPA remnants) or an old PSK, which NetworkManager stores only when
# "connection up" below supplies it.
run_as_root nmcli connection delete "${CON_NAME}" >/dev/null 2>&1 || true
run_as_root nmcli connection add type wifi ifname "${IFNAME}" con-name "${CON_NAME}" autoconnect yes ssid "${SSID}"

run_as_root nmcli connection modify "${CON_NAME}" \
  802-11-wireless.mode ap \
  802-11-wireless.band bg \
  802-11-wireless.channel "${CHANNEL}" \
  ipv4.method shared \
  ipv4.addresses "${IP}" \
  ipv6.method ignore

if [ -n "${PSK}" ]; then
  run_as_root nmcli connection modify "${CON_NAME}" 802-11-wireless-security.key-mgmt wpa-psk
fi

bring_up_hotspot() {
  if [ -z "${PSK}" ]; then
    run_as_root nmcli connection up "${CON_NAME}"
    return
  fi
  # The PSK goes to nmcli as a passwd-file through a pipe, never on a command
  # line, where any local user could read it from /proc/<pid>/cmdline.
  run_as_root nmcli connection up "${CON_NAME}" \
    passwd-file <(/usr/bin/python3 -I "${SCRIPT_DIR}/vibesensor_hotspot.py" passwd-file "${CONFIG_PATH}")
}

if ! bring_up_hotspot; then
  echo "AP connection bring-up failed for ${CON_NAME}"
  dump_all ap_failed
  write_summary FAILED 22
  exit 22
fi

run_as_root nmcli -f GENERAL.STATE,IP4.ADDRESS connection show "${CON_NAME}"
dump_all post
write_summary OK 0
