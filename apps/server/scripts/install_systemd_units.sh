#!/usr/bin/env bash
# Install VibeSensor's systemd units and the root-side privileged helper.
#
# Usage (as root): install_systemd_units.sh [SERVICE_USER]
#
# install_pi.sh runs this. On a device installed before the privileged helper
# existed, copy the new apps/server/scripts and apps/server/systemd onto the
# device and run this once to migrate (docs/operational-runbooks.md). It needs
# no network. SERVICE_USER defaults to the User= of the installed
# vibesensor.service. VIBESENSOR_SKIP_SERVICE_START=1 only enables units
# (image builds and chroots).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${PI_DIR}/.venv"
UNIT_DIR=/etc/systemd/system
SKIP_SERVICE_START="${VIBESENSOR_SKIP_SERVICE_START:-0}"
SERVICE_USER="${1:-}"
if [ -z "${SERVICE_USER}" ]; then
  SERVICE_USER="$(systemctl show --property=User --value vibesensor.service 2>/dev/null || true)"
fi
if [ -z "${SERVICE_USER}" ]; then
  echo "ERROR: pass the service user; no installed vibesensor.service names one." >&2
  exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: $0 must run as root." >&2
  exit 1
fi

# Root runs these for the server (vibesensor-privileged@.service); the
# allowlist wrappers are the security boundary for every request.
for privileged_script in \
  "${SCRIPT_DIR}/vibesensor_privileged_helper.py" \
  "${SCRIPT_DIR}/vibesensor_update_allowlist.sh" \
  "${SCRIPT_DIR}/vibesensor_obd_admin.py"; do
  if [ ! -f "${privileged_script}" ]; then
    echo "ERROR: Missing privileged helper script ${privileged_script}." >&2
    exit 1
  fi
  chmod 0755 "${privileged_script}"
done
# Installs before the privileged helper granted the service user sudo on a
# wrapper. The service runs with NoNewPrivileges=true, so sudo never worked
# from it; remove the stale grant and wrapper.
rm -f /etc/sudoers.d/vibesensor-update "${SCRIPT_DIR}/vibesensor_update_sudo.sh"

render_unit() {
  local name="$1"
  sed \
    -e "s#__PI_DIR__#${PI_DIR}#g" \
    -e "s#__VENV_DIR__#${VENV_DIR}#g" \
    -e "s#__SERVICE_USER__#${SERVICE_USER}#g" \
    "${PI_DIR}/systemd/${name}" >"${UNIT_DIR}/${name}"
  chmod 0644 "${UNIT_DIR}/${name}"
}

for unit in \
  vibesensor.service \
  vibesensor-privileged.socket \
  vibesensor-privileged@.service \
  vibesensor-hotspot.service \
  vibesensor-hotspot-self-heal.service \
  vibesensor-hotspot-self-heal.timer; do
  render_unit "${unit}"
done

enable_unit() {
  local unit="$1" target="$2"
  if ! systemctl enable "${unit}" >/dev/null 2>&1; then
    install -d "${UNIT_DIR}/${target}.wants"
    ln -sf "${UNIT_DIR}/${unit}" "${UNIT_DIR}/${target}.wants/${unit}"
  fi
}

if [ "${SKIP_SERVICE_START}" = "1" ]; then
  # Image-build and chroot installs cannot start services, so enable them via symlinks only.
  systemctl daemon-reload >/dev/null 2>&1 || true
  enable_unit vibesensor-privileged.socket sockets.target
  enable_unit vibesensor.service multi-user.target
  enable_unit vibesensor-hotspot.service multi-user.target
  enable_unit vibesensor-hotspot-self-heal.timer timers.target
else
  systemctl daemon-reload
  systemctl enable --now vibesensor-privileged.socket
  # Restart (not just start) so a re-run applies the updated unit to a running server.
  systemctl enable vibesensor.service
  systemctl restart vibesensor.service
  systemctl enable --now vibesensor-hotspot.service
  systemctl enable --now vibesensor-hotspot-self-heal.timer
  systemctl status vibesensor.service --no-pager
fi
