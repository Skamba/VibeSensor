#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CACHE_DIR="${SCRIPT_DIR}/.cache"
PI_GEN_DIR="${CACHE_DIR}/pi-gen"
PI_GEN_REF="${PI_GEN_REF:-bookworm}"
STAGE_DIR="${PI_GEN_DIR}/stage-vibesensor"
STAGE_STEP_DIR="${STAGE_DIR}/00-vibesensor"
STAGE_REPO_DIR="${STAGE_STEP_DIR}/files/opt/VibeSensor"
OUT_DIR="${SCRIPT_DIR}/out"
IMG_SUFFIX_BASE="-vibesensor-lite"

if [ "${USE_QEMU:-0}" = "1" ]; then
  IMG_SUFFIX="${IMG_SUFFIX_BASE}-qemu"
else
  IMG_SUFFIX="${IMG_SUFFIX_BASE}"
fi

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    exit 1
  fi
}

require_cmd git
require_cmd docker
require_cmd rsync
require_cmd sudo
require_cmd losetup
require_cmd mount
require_cmd umount
require_cmd awk

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not available for current user."
  echo "Start Docker and/or add your user to the docker group."
  exit 1
fi

mkdir -p "${CACHE_DIR}" "${OUT_DIR}"

if [ ! -d "${PI_GEN_DIR}/.git" ]; then
  git clone --depth 1 --branch "${PI_GEN_REF}" https://github.com/RPi-Distro/pi-gen.git "${PI_GEN_DIR}"
else
  git -C "${PI_GEN_DIR}" fetch --depth 1 origin "${PI_GEN_REF}"
  git -C "${PI_GEN_DIR}" checkout -B "${PI_GEN_REF}" FETCH_HEAD
  git -C "${PI_GEN_DIR}" reset --hard FETCH_HEAD
fi

rm -rf "${STAGE_DIR}"
mkdir -p "${STAGE_REPO_DIR}"

cat >"${STAGE_DIR}/prerun.sh" <<'EOF'
#!/bin/bash -e

if [ ! -d "${ROOTFS_DIR}" ]; then
  copy_previous
fi
EOF
chmod +x "${STAGE_DIR}/prerun.sh"

rsync -a --delete \
  --exclude ".git/" \
  --exclude ".venv/" \
  --exclude "__pycache__/" \
  --exclude "*.pyc" \
  --exclude "image/pi-gen/.cache/" \
  --exclude "image/pi-gen/out/" \
  "${REPO_ROOT}/" "${STAGE_REPO_DIR}/"

cat >"${STAGE_STEP_DIR}/00-run.sh" <<'EOF'
#!/bin/bash -e

install -d "${ROOTFS_DIR}/opt"
cp -a files/opt/VibeSensor "${ROOTFS_DIR}/opt/"

install -d "${ROOTFS_DIR}/etc/vibesensor" "${ROOTFS_DIR}/var/lib/vibesensor" "${ROOTFS_DIR}/var/log/vibesensor"
install -d "${ROOTFS_DIR}/etc/systemd/system"

if [ ! -f "${ROOTFS_DIR}/etc/vibesensor/config.yaml" ]; then
  install -m 0644 \
    "${ROOTFS_DIR}/opt/VibeSensor/pi/config.example.yaml" \
    "${ROOTFS_DIR}/etc/vibesensor/config.yaml"
fi

if [ ! -f "${ROOTFS_DIR}/etc/vibesensor/wifi-secrets.env" ]; then
  install -m 0600 \
    "${ROOTFS_DIR}/opt/VibeSensor/pi/wifi-secrets.example.env" \
    "${ROOTFS_DIR}/etc/vibesensor/wifi-secrets.env"
fi

install -m 0644 \
  "${ROOTFS_DIR}/opt/VibeSensor/image/pi-gen/assets/vibesensor-hotspot.service" \
  "${ROOTFS_DIR}/etc/systemd/system/vibesensor-hotspot.service"

install -m 0644 \
  "${ROOTFS_DIR}/opt/VibeSensor/image/pi-gen/assets/vibesensor-hotspot-self-heal.service" \
  "${ROOTFS_DIR}/etc/systemd/system/vibesensor-hotspot-self-heal.service"

install -m 0644 \
  "${ROOTFS_DIR}/opt/VibeSensor/image/pi-gen/assets/vibesensor-hotspot-self-heal.timer" \
  "${ROOTFS_DIR}/etc/systemd/system/vibesensor-hotspot-self-heal.timer"

sed \
  -e 's#__PI_DIR__#/opt/VibeSensor/pi#g' \
  -e 's#__VENV_DIR__#/opt/VibeSensor/pi/.venv#g' \
  -e 's#__SERVICE_USER__#pi#g' \
  "${ROOTFS_DIR}/opt/VibeSensor/pi/systemd/vibesensor.service" >"${ROOTFS_DIR}/etc/systemd/system/vibesensor.service"

mkdir -p "${ROOTFS_DIR}/etc/systemd/system/multi-user.target.wants"
ln -sf /etc/systemd/system/vibesensor.service \
  "${ROOTFS_DIR}/etc/systemd/system/multi-user.target.wants/vibesensor.service"
ln -sf /etc/systemd/system/vibesensor-hotspot.service \
  "${ROOTFS_DIR}/etc/systemd/system/multi-user.target.wants/vibesensor-hotspot.service"
mkdir -p "${ROOTFS_DIR}/etc/systemd/system/timers.target.wants"
ln -sf /etc/systemd/system/vibesensor-hotspot-self-heal.timer \
  "${ROOTFS_DIR}/etc/systemd/system/timers.target.wants/vibesensor-hotspot-self-heal.timer"
EOF
chmod +x "${STAGE_STEP_DIR}/00-run.sh"

# Ensure this custom stage is exported as the final image artifact.
touch "${STAGE_DIR}/EXPORT_IMAGE"

# Avoid accidentally exporting stock stage2 images that could be flashed by mistake.
touch "${PI_GEN_DIR}/stage2/SKIP_IMAGES"

cat >"${PI_GEN_DIR}/config" <<EOF
# This image is tuned for Raspberry Pi 3 A+ deployments.
IMG_NAME='vibesensor-rpi3a-plus-bookworm-lite'
IMG_SUFFIX='${IMG_SUFFIX}'
RELEASE='bookworm'
ENABLE_SSH=1
STAGE_LIST="stage0 stage1 stage2 stage-vibesensor"
EOF

(
  cd "${PI_GEN_DIR}"
  if docker ps -a --format '{{.Names}}' | grep -Fxq pigen_work; then
    docker rm -v pigen_work >/dev/null
  fi
  ./build-docker.sh
)

find "${PI_GEN_DIR}/deploy" -maxdepth 1 -type f \
  \( -name "*${IMG_SUFFIX}*.img" -o -name "*${IMG_SUFFIX}*.img.xz" -o -name "*${IMG_SUFFIX}*.zip" -o -name "*${IMG_SUFFIX}*.sha256" \) \
  -exec cp -f {} "${OUT_DIR}/" \;

if ! find "${OUT_DIR}" -maxdepth 1 -type f \( -name "*${IMG_SUFFIX}*.img" -o -name "*${IMG_SUFFIX}*.img.xz" -o -name "*${IMG_SUFFIX}*.zip" \) | grep -q .; then
  echo "No exported image artifacts matching IMG_SUFFIX='${IMG_SUFFIX}' were copied to ${OUT_DIR}"
  exit 1
fi

choose_final_artifact() {
  local base_dir="$1"
  local candidate=""

  candidate="$(find "${base_dir}" -maxdepth 1 -type f -name "*${IMG_SUFFIX}*.img" | sort | head -n 1 || true)"
  if [ -n "${candidate}" ]; then
    printf '%s\n' "${candidate}"
    return 0
  fi

  candidate="$(find "${base_dir}" -maxdepth 1 -type f -name "*${IMG_SUFFIX}*.img.xz" | sort | head -n 1 || true)"
  if [ -n "${candidate}" ]; then
    printf '%s\n' "${candidate}"
    return 0
  fi

  candidate="$(find "${base_dir}" -maxdepth 1 -type f -name "*${IMG_SUFFIX}*.zip" | sort | head -n 1 || true)"
  if [ -n "${candidate}" ]; then
    printf '%s\n' "${candidate}"
    return 0
  fi

  return 1
}

FINAL_ARTIFACT="$(choose_final_artifact "${OUT_DIR}")"
if [ -z "${FINAL_ARTIFACT}" ]; then
  echo "Failed to select a final artifact in ${OUT_DIR}"
  exit 1
fi

INSPECT_DIR="${OUT_DIR}/inspect"
mkdir -p "${INSPECT_DIR}"
INSPECT_IMG="${FINAL_ARTIFACT}"

case "${FINAL_ARTIFACT}" in
  *.img)
    ;;
  *.img.xz)
    require_cmd xz
    INSPECT_IMG="${FINAL_ARTIFACT%.xz}"
    xz -dkf "${FINAL_ARTIFACT}"
    ;;
  *.zip)
    require_cmd unzip
    unzip -o "${FINAL_ARTIFACT}" -d "${INSPECT_DIR}" >/dev/null
    INSPECT_IMG="$(find "${INSPECT_DIR}" -maxdepth 1 -type f -name "*.img" | sort | head -n 1 || true)"
    if [ -z "${INSPECT_IMG}" ]; then
      echo "ZIP artifact did not contain an .img file: ${FINAL_ARTIFACT}"
      exit 1
    fi
    ;;
  *)
    echo "Unsupported artifact format: ${FINAL_ARTIFACT}"
    exit 1
    ;;
esac

if [ ! -f "${INSPECT_IMG}" ]; then
  echo "Inspection image does not exist: ${INSPECT_IMG}"
  exit 1
fi

MOUNT_DIR="${OUT_DIR}/mount"
BOOT_MNT="${MOUNT_DIR}/boot"
ROOT_MNT="${MOUNT_DIR}/root"
mkdir -p "${BOOT_MNT}" "${ROOT_MNT}"

LOOP_DEV=""
cleanup_mounts() {
  set +e
  if mountpoint -q "${ROOT_MNT}"; then
    sudo umount "${ROOT_MNT}"
  fi
  if mountpoint -q "${BOOT_MNT}"; then
    sudo umount "${BOOT_MNT}"
  fi
  if [ -n "${LOOP_DEV}" ]; then
    sudo losetup -d "${LOOP_DEV}"
  fi
}
trap cleanup_mounts EXIT

LOOP_DEV="$(sudo losetup -Pf --show "${INSPECT_IMG}")"
sudo mount "${LOOP_DEV}p1" "${BOOT_MNT}"
sudo mount "${LOOP_DEV}p2" "${ROOT_MNT}"

if [ ! -d "${ROOT_MNT}/opt/VibeSensor" ]; then
  echo "Validation failed: missing ${ROOT_MNT}/opt/VibeSensor"
  exit 1
fi

if [ ! -f "${ROOT_MNT}/etc/systemd/system/vibesensor-hotspot.service" ]; then
  echo "Validation failed: missing ${ROOT_MNT}/etc/systemd/system/vibesensor-hotspot.service"
  exit 1
fi

if [ ! -d "${ROOT_MNT}/etc/vibesensor" ]; then
  echo "Validation failed: missing ${ROOT_MNT}/etc/vibesensor"
  exit 1
fi

echo "=== Validation: /opt/VibeSensor exists ==="
ls -la "${ROOT_MNT}/opt/VibeSensor" | head -n 20

echo "=== Validation: vibesensor systemd units ==="
ls -la "${ROOT_MNT}/etc/systemd/system" | grep -i vibesensor || true

echo "=== Validation: /etc/vibesensor ==="
ls -la "${ROOT_MNT}/etc/vibesensor"

cleanup_mounts
trap - EXIT

mkdir -p /mnt/c/temp
cp -f "${FINAL_ARTIFACT}" /mnt/c/temp/

echo "Image artifacts available in: ${OUT_DIR}"
echo "Final artifact: ${FINAL_ARTIFACT}"
echo "Copied artifact to: /mnt/c/temp/$(basename "${FINAL_ARTIFACT}")"
