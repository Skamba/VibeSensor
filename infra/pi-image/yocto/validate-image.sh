#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACT="${1:-$(find "${SCRIPT_DIR}/out" -maxdepth 1 -type f -name 'image_*vibesensor-rpi-universal.wic.bz2' | sort | tail -n 1 || true)}"
VS_FIRST_USER_NAME="${VS_FIRST_USER_NAME:-pi}"
VS_FIRST_USER_PASS="${VS_FIRST_USER_PASS:-vibesensor}"
if [ -z "${ARTIFACT}" ] || [ ! -f "${ARTIFACT}" ]; then
  echo "Usage: $0 /path/to/image.wic.bz2" >&2
  exit 1
fi

WORK_DIR="${SCRIPT_DIR}/out/inspect"
MOUNT_DIR="${SCRIPT_DIR}/out/mount"
BOOT_MNT="${MOUNT_DIR}/boot"
ROOT_MNT="${MOUNT_DIR}/root"
mkdir -p "${WORK_DIR}" "${BOOT_MNT}" "${ROOT_MNT}"

case "${ARTIFACT}" in
  *.wic.bz2|*.img.bz2)
    command -v bzip2 >/dev/null 2>&1 || { echo "bzip2 required" >&2; exit 1; }
    IMG_PATH="${WORK_DIR}/$(basename "${ARTIFACT%.*.*}")"
    bzip2 -dkfc "${ARTIFACT}" > "${IMG_PATH}"
    ;;
  *.wic|*.img)
    IMG_PATH="${ARTIFACT}"
    ;;
  *)
    echo "Unsupported artifact format: ${ARTIFACT}" >&2
    exit 1
    ;;
esac

LOOP_DEV=""
cleanup() {
  set +e
  mountpoint -q "${ROOT_MNT}" && sudo umount "${ROOT_MNT}"
  mountpoint -q "${BOOT_MNT}" && sudo umount "${BOOT_MNT}"
  [ -n "${LOOP_DEV}" ] && sudo losetup -d "${LOOP_DEV}"
}
trap cleanup EXIT

LOOP_DEV="$(sudo losetup -Pf --show "${IMG_PATH}")"
sudo mount "${LOOP_DEV}p1" "${BOOT_MNT}"
sudo mount "${LOOP_DEV}p2" "${ROOT_MNT}"

assert_file() {
  [ -e "$1" ] || { echo "Validation failed: missing $1" >&2; exit 1; }
}

assert_exec_in_root() {
  local name="$1"
  local path=""
  for candidate in /usr/bin/${name} /usr/sbin/${name} /bin/${name} /sbin/${name}; do
    if [ -x "${ROOT_MNT}${candidate}" ]; then
      path="${candidate}"
      break
    fi
  done
  [ -n "${path}" ] || { echo "Validation failed: missing executable ${name}" >&2; exit 1; }
}

assert_file "${ROOT_MNT}/opt/VibeSensor"
assert_file "${ROOT_MNT}/etc/vibesensor/config.yaml"
assert_file "${ROOT_MNT}/var/lib/vibesensor"
assert_file "${ROOT_MNT}/var/log/vibesensor"
assert_file "${ROOT_MNT}/opt/VibeSensor/apps/server/scripts/hotspot_nmcli.sh"
assert_file "${ROOT_MNT}/opt/VibeSensor/apps/server/scripts/vibesensor_update_sudo.sh"
assert_file "${ROOT_MNT}/opt/VibeSensor/apps/server/data/report_i18n.json"
assert_file "${ROOT_MNT}/opt/VibeSensor/apps/server/data/car_library.json"
assert_file "${ROOT_MNT}/opt/VibeSensor/apps/server/.venv/bin/python"
assert_file "${ROOT_MNT}/usr/lib/systemd/system/vibesensor.service"
assert_file "${ROOT_MNT}/usr/lib/systemd/system/vibesensor-hotspot.service"
assert_file "${ROOT_MNT}/usr/lib/systemd/system/vibesensor-hotspot-self-heal.service"
assert_file "${ROOT_MNT}/usr/lib/systemd/system/vibesensor-hotspot-self-heal.timer"
assert_file "${ROOT_MNT}/usr/lib/systemd/system/vibesensor-rfkill-unblock.service"
assert_file "${ROOT_MNT}/usr/lib/systemd/system/vibesensor-ssh-hostkeys.service"
assert_file "${ROOT_MNT}/etc/systemd/system/sshd.service.d/10-vibesensor-hostkeys.conf"
assert_file "${ROOT_MNT}/etc/ssh/sshd_config.d/99-vibesensor-password-auth.conf"
assert_file "${ROOT_MNT}/etc/NetworkManager/conf.d/99-vibesensor-dnsmasq.conf"
assert_file "${ROOT_MNT}/etc/tmpfiles.d/vibesensor-wifi.conf"
assert_file "${ROOT_MNT}/etc/sudoers.d/vibesensor-update"
if ! grep -E "^${VS_FIRST_USER_NAME}:" "${ROOT_MNT}/etc/passwd" >/dev/null 2>&1; then
  echo "Validation failed: expected user '${VS_FIRST_USER_NAME}' missing from /etc/passwd" >&2
  exit 1
fi
SHADOW_LINE="$(sudo grep -E "^${VS_FIRST_USER_NAME}:" "${ROOT_MNT}/etc/shadow" || true)"
if [ -z "${SHADOW_LINE}" ] || [ "${SHADOW_LINE#*:}" = "${SHADOW_LINE}" ]; then
  echo "Validation failed: first user '${VS_FIRST_USER_NAME}' has no usable password hash" >&2
  exit 1
fi
SHADOW_HASH="$(printf '%s\n' "${SHADOW_LINE}" | cut -d: -f2)"
EXPECTED_HASH="$(openssl passwd -6 -salt vibesensor "${VS_FIRST_USER_PASS}")"
if [ "${SHADOW_HASH}" != "${EXPECTED_HASH}" ]; then
  echo "Validation failed: first user password hash does not match VS_FIRST_USER_PASS" >&2
  exit 1
fi
if ! grep -Fx "${VS_FIRST_USER_NAME} ALL=(root) NOPASSWD: /opt/VibeSensor/apps/server/scripts/vibesensor_update_sudo.sh" \
  "${ROOT_MNT}/etc/sudoers.d/vibesensor-update" >/dev/null 2>&1; then
  echo "Validation failed: sudoers does not grant updater access to ${VS_FIRST_USER_NAME}" >&2
  exit 1
fi
assert_exec_in_root nmcli
assert_exec_in_root rfkill
assert_exec_in_root iw
assert_exec_in_root dnsmasq
assert_exec_in_root gpsd
assert_exec_in_root usbmuxd

if [ -d "${ROOT_MNT}/opt/VibeSensor/apps/server/vibesensor" ]; then
  echo "Validation failed: source tree still present under /opt/VibeSensor/apps/server/vibesensor" >&2
  exit 1
fi
if grep -n 'apt-get' "${ROOT_MNT}/opt/VibeSensor/apps/server/scripts/hotspot_nmcli.sh" >/dev/null 2>&1; then
  echo "Validation failed: hotspot script still contains apt-get" >&2
  exit 1
fi
if ! grep -n '/var/log/wifi' "${ROOT_MNT}/opt/VibeSensor/apps/server/scripts/hotspot_nmcli.sh" >/dev/null 2>&1; then
  echo "Validation failed: hotspot script does not reference /var/log/wifi" >&2
  exit 1
fi
if [ -d "${ROOT_MNT}/var/lib/vibesensor/firmware/baseline" ] && [ ! -f "${ROOT_MNT}/var/lib/vibesensor/firmware/baseline/flash.json" ]; then
  echo "Validation failed: firmware baseline directory exists without flash.json" >&2
  exit 1
fi

run_chroot() {
  if [ "$(uname -m)" = "aarch64" ]; then
    sudo chroot "${ROOT_MNT}" "$@"
  else
    sudo cp "$(command -v qemu-aarch64-static)" "${ROOT_MNT}/usr/bin/"
    sudo chroot "${ROOT_MNT}" /usr/bin/qemu-aarch64-static "$@"
  fi
}

run_chroot /opt/VibeSensor/apps/server/.venv/bin/python - <<'PY'
import importlib

mods = [
    "numpy",
    "yaml",
    "reportlab",
    "fastapi",
    "uvicorn",
    "vibesensor",
    "vibesensor.vibration_strength",
]
for mod in mods:
    importlib.import_module(mod)
print("IMPORT_VALIDATION_OK")
PY

run_chroot /bin/bash -lc '
set -e
cp /etc/vibesensor/config.yaml /tmp/vibesensor-smoke-config.yaml
/opt/VibeSensor/apps/server/.venv/bin/python - <<\"PY\"
from pathlib import Path
import yaml

path = Path("/tmp/vibesensor-smoke-config.yaml")
config = yaml.safe_load(path.read_text())
server = config.setdefault("server", {})
udp = config.setdefault("udp", {})
server["port"] = 18080
udp["data_host"] = "0.0.0.0"
udp["data_port"] = 19000
udp["control_host"] = "0.0.0.0"
udp["control_port"] = 19001
path.write_text(yaml.safe_dump(config, sort_keys=False))
PY
set +e
timeout 10s /opt/VibeSensor/apps/server/.venv/bin/vibesensor-server --config /tmp/vibesensor-smoke-config.yaml >/tmp/vibesensor-smoke.log 2>&1
code=$?
set -e
if [ "$code" -ne 0 ] && [ "$code" -ne 124 ]; then
  tail -n 80 /tmp/vibesensor-smoke.log || true
  exit 1
fi
grep -q "Application startup complete" /tmp/vibesensor-smoke.log
'

echo "Yocto image validation OK: ${ARTIFACT}"
