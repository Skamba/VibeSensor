#!/usr/bin/env bash
# Install VibeSensor's systemd units and the root-side helpers.
#
# Usage (as root): install_systemd_units.sh [SERVICE_USER]
#
# install_pi.sh and the Pi image build run this. Root only ever executes
# root-owned code: this script copies apps/server/root-helpers/ into
# /usr/local/lib/vibesensor (root:root, 0755), and every root unit and the
# privileged helper run from there under the system /usr/bin/python3 -I. Root
# never runs anything from the install tree, the A/B venv, or a clone the
# service user can write. OTA app updates replace only the venv, so a release
# that changes root-helpers/ or systemd/ takes effect when this script runs
# again from that release's tree (docs/operational-runbooks.md, "Installing a
# release's root side"); it needs no network. SERVICE_USER defaults to the User= of the installed
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

ROOT_HELPER_SRC="${PI_DIR}/root-helpers"
ROOT_HELPER_DIR=/usr/local/lib/vibesensor
if [ ! -f "${ROOT_HELPER_SRC}/vibesensor_privileged_helper.py" ]; then
  echo "ERROR: Missing root-side helpers in ${ROOT_HELPER_SRC}." >&2
  exit 1
fi
# Stage a complete root-owned copy, then swap it in, so a running helper never
# sees a half-installed directory and files removed from root-helpers/ go away.
install -d -o root -g root -m 0755 "$(dirname "${ROOT_HELPER_DIR}")"
rm -rf "${ROOT_HELPER_DIR}.new"
install -d -o root -g root -m 0755 "${ROOT_HELPER_DIR}.new"
for helper in "${ROOT_HELPER_SRC}"/*; do
  # Regular files only (a dev checkout may hold a __pycache__ directory), never
  # symlinks: the manifest below covers exactly these files.
  if [ -f "${helper}" ] && [ ! -L "${helper}" ]; then
    install -o root -g root -m 0755 "${helper}" "${ROOT_HELPER_DIR}.new/"
  fi
done
rm -rf "${ROOT_HELPER_DIR}.old"
if [ -d "${ROOT_HELPER_DIR}" ]; then
  mv "${ROOT_HELPER_DIR}" "${ROOT_HELPER_DIR}.old"
fi
mv "${ROOT_HELPER_DIR}.new" "${ROOT_HELPER_DIR}"
rm -rf "${ROOT_HELPER_DIR}.old"
# Earlier installs ran root helpers from apps/server/scripts (and before that
# granted sudo on a wrapper, which never worked under NoNewPrivileges=true).
# Remove those copies so nothing root-side is left in the install tree.
rm -f /etc/sudoers.d/vibesensor-update
for stale in vibesensor_update_sudo.sh vibesensor_privileged_helper.py \
  vibesensor_update_allowlist.sh vibesensor_obd_admin.py hotspot_nmcli.sh; do
  rm -f "${SCRIPT_DIR}/${stale}"
done

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

# Record what is now installed: the manifest of the root side this ran from
# (sha256sum lines for the regular files in root-helpers/, scripts/ and
# systemd/, sorted bytewise). The server compares its digest with the one its
# release ships and reports an outdated root side in /api/health
# (vibesensor/common/root_side.py). Written last, so an install that stops
# half way leaves no stamp and shows as outdated.
(
  cd "${PI_DIR}"
  find root-helpers scripts systemd -maxdepth 1 -type f -exec sha256sum {} + | LC_ALL=C sort
) >"${ROOT_HELPER_DIR}/root-side.sha256.new"
chmod 0644 "${ROOT_HELPER_DIR}/root-side.sha256.new"
mv -f "${ROOT_HELPER_DIR}/root-side.sha256.new" "${ROOT_HELPER_DIR}/root-side.sha256"

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
