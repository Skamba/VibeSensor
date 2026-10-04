#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVER_PYPROJECT="${PI_DIR}/pyproject.toml"
RUNTIME_POLICY_DOC="docs/runtime_support_matrix.md"
VENV_DIR="${PI_DIR}/.venv"
SKIP_SERVICE_START="${VIBESENSOR_SKIP_SERVICE_START:-0}"

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

if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
  SERVICE_USER="${SUDO_USER}"
elif id -u pi >/dev/null 2>&1; then
  SERVICE_USER="pi"
else
  SERVICE_USER="$(id -un)"
fi

run_as_service_user() {
  if [ "$(id -u)" -eq 0 ]; then
    runuser -u "${SERVICE_USER}" -- "$@"
  else
    sudo -u "${SERVICE_USER}" "$@"
  fi
}

read_supported_python_floor() {
  local floor
  floor="$(
    sed -n 's/^requires-python = ">=\([0-9][0-9]*\.[0-9][0-9]*\)"$/\1/p' "${SERVER_PYPROJECT}" | head -n 1
  )"
  if [ -z "${floor}" ]; then
    echo "ERROR: Could not determine the supported Python floor from ${SERVER_PYPROJECT}." >&2
    exit 1
  fi
  printf '%s\n' "${floor}"
}

validate_supported_python() {
  local python_bin="$1"
  local supported_floor actual_version actual_major actual_minor required_major required_minor
  supported_floor="$(read_supported_python_floor)"
  actual_version="$("${python_bin}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
  IFS=. read -r actual_major actual_minor _ <<<"${actual_version}"
  IFS=. read -r required_major required_minor <<<"${supported_floor}"

  if [ -z "${actual_major:-}" ] || [ -z "${actual_minor:-}" ]; then
    echo "ERROR: Could not parse the installed python3 version reported by ${python_bin}: ${actual_version}" >&2
    exit 1
  fi

  if [ "${actual_major}" -lt "${required_major}" ] || {
    [ "${actual_major}" -eq "${required_major}" ] && [ "${actual_minor}" -lt "${required_minor}" ];
  }; then
    echo "ERROR: install_pi.sh requires python3 >= ${supported_floor}; found ${actual_version} at ${python_bin}. See ${RUNTIME_POLICY_DOC} for the supported Raspberry Pi runtime policy." >&2
    exit 1
  fi
}

run_as_root apt-get update
run_as_root apt-get install -y \
  python3 \
  python3-venv \
  python3-pip \
  libopenblas0-pthread \
  network-manager \
  dnsmasq-base \
  rfkill \
  iw \
  gpsd \
  gpsd-clients

PYTHON_BIN="$(command -v python3 || true)"
if [ -z "${PYTHON_BIN}" ]; then
  echo "ERROR: python3 is not available after package installation." >&2
  exit 1
fi
validate_supported_python "${PYTHON_BIN}"

"${PYTHON_BIN}" -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -e "${PI_DIR}"
# Move the venv into an A/B slot so OTA updates can install beside it (no-op on reruns).
"${VENV_DIR}/bin/python" -m vibesensor.updates.venv_slots adopt "${VENV_DIR}"
"${VENV_DIR}/bin/vibesensor-config-preflight" "${PI_DIR}/config.pi.yaml" >/dev/null

run_as_root install -d /etc/vibesensor
run_as_root install -d /etc/tmpfiles.d
run_as_root install -d -m 0755 /var/lib/vibesensor
run_as_root install -d -m 0755 /var/log/vibesensor
run_as_root install -d -m 0755 /var/log/wifi
run_as_root chown "${SERVICE_USER}:${SERVICE_USER}" /var/lib/vibesensor /var/log/vibesensor
run_as_root chown -R "${SERVICE_USER}:${SERVICE_USER}" "${VENV_DIR}"

# Refresh ESP firmware cache from GitHub Releases (requires network).
# This downloads the latest prebuilt firmware bundle so the device can flash
# ESP32 chips offline.  The embedded baseline (if present in the Pi image)
# remains available as a fallback.
echo "Refreshing ESP firmware cache..."
run_as_service_user "${VENV_DIR}/bin/vibesensor-fw-refresh" \
  --cache-dir /var/lib/vibesensor/firmware || \
  echo "WARNING: ESP firmware cache refresh failed. Flashing will use embedded baseline if available."

run_as_root tee /etc/tmpfiles.d/vibesensor-wifi.conf >/dev/null <<'EOF'
d /var/log/wifi 0755 root root -
EOF
run_as_root systemd-tmpfiles --create /etc/tmpfiles.d/vibesensor-wifi.conf >/dev/null 2>&1 || true
if [ ! -f /etc/vibesensor/config.yaml ]; then
  run_as_root cp "${PI_DIR}/config.pi.yaml" /etc/vibesensor/config.yaml
fi

# Units, the privileged helper, and service start-up (also the offline
# migration path for devices installed before the privileged helper).
run_as_root env VIBESENSOR_SKIP_SERVICE_START="${SKIP_SERVICE_START}" \
  "${SCRIPT_DIR}/install_systemd_units.sh" "${SERVICE_USER}"
