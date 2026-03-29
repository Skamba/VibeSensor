#!/usr/bin/env bash
set -euo pipefail

: "${IMAGE_ROOTFS:?missing IMAGE_ROOTFS}"
VIBESENSOR_SERVICE_USER="${VIBESENSOR_SERVICE_USER:-pi}"

QEMU_STATIC="${HOST_QEMU_AARCH64:-}"
if [ "$(uname -m)" = "aarch64" ]; then
  QEMU_STATIC=""
elif [ -z "${QEMU_STATIC}" ]; then
  QEMU_STATIC="$(command -v qemu-aarch64-static || true)"
fi

chroot_exec() {
  if [ -n "${QEMU_STATIC}" ]; then
    chroot "${IMAGE_ROOTFS}" /usr/bin/qemu-aarch64-static "$@"
  else
    chroot "${IMAGE_ROOTFS}" "$@"
  fi
}

if [ -n "${QEMU_STATIC}" ]; then
  install -m 0755 "${QEMU_STATIC}" "${IMAGE_ROOTFS}/usr/bin/qemu-aarch64-static"
fi

VENV_DIR="/opt/VibeSensor/apps/server/.venv"
WHEEL_DIR="/opt/vibesensor-artifacts/wheels"
APP_WHEEL="$(basename "$(find "${IMAGE_ROOTFS}${WHEEL_DIR}" -maxdepth 1 -type f -name 'vibesensor-*.whl' | sort | tail -n 1)")"

if [ -z "${APP_WHEEL}" ]; then
  echo "Missing vibesensor wheel under ${IMAGE_ROOTFS}${WHEEL_DIR}" >&2
  exit 1
fi

export PSEUDO_UNLOAD=1
chroot_exec /usr/bin/python3 -m venv --system-site-packages "${VENV_DIR}"
chroot_exec "${VENV_DIR}/bin/python" -m pip install --no-index --find-links "${WHEEL_DIR}" pip setuptools wheel
chroot_exec "${VENV_DIR}/bin/python" -m pip install --no-index --find-links "${WHEEL_DIR}" "${WHEEL_DIR}/${APP_WHEEL}[esp]"

if [ -d "${IMAGE_ROOTFS}/opt/VibeSensor/apps/server/vibesensor" ]; then
  rm -rf "${IMAGE_ROOTFS}/opt/VibeSensor/apps/server/vibesensor"
fi
rm -rf \
  "${IMAGE_ROOTFS}/opt/VibeSensor/apps/server/tests" \
  "${IMAGE_ROOTFS}/opt/VibeSensor/apps/server/tests_e2e" \
  "${IMAGE_ROOTFS}/opt/VibeSensor/apps/ui" \
  "${IMAGE_ROOTFS}/opt/VibeSensor/docs" \
  "${IMAGE_ROOTFS}/opt/VibeSensor/examples" \
  "${IMAGE_ROOTFS}/opt/VibeSensor/firmware" \
  "${IMAGE_ROOTFS}/opt/VibeSensor/hardware" \
  "${IMAGE_ROOTFS}/opt/VibeSensor/.git" \
  "${IMAGE_ROOTFS}/opt/VibeSensor/.github" \
  "${IMAGE_ROOTFS}/opt/vibesensor-artifacts/wheels"

chroot_exec /bin/chown -R "${VIBESENSOR_SERVICE_USER}:${VIBESENSOR_SERVICE_USER}" /var/lib/vibesensor /var/log/vibesensor "${VENV_DIR}"
chroot_exec /bin/chown -R "${VIBESENSOR_SERVICE_USER}:${VIBESENSOR_SERVICE_USER}" /opt/VibeSensor
