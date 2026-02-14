#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CACHE_DIR="${SCRIPT_DIR}/.cache"
PI_GEN_DIR="${CACHE_DIR}/pi-gen"
PI_GEN_REF="${PI_GEN_REF:-bookworm}"
STAGE_DIR="${PI_GEN_DIR}/stage-vibesensor"
STAGE_REPO_DIR="${STAGE_DIR}/files/opt/VibeSensor"
OUT_DIR="${SCRIPT_DIR}/out"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    exit 1
  fi
}

require_cmd git
require_cmd docker
require_cmd rsync

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

rsync -a --delete \
  --exclude ".git/" \
  --exclude ".venv/" \
  --exclude "__pycache__/" \
  --exclude "*.pyc" \
  --exclude "image/pi-gen/.cache/" \
  --exclude "image/pi-gen/out/" \
  "${REPO_ROOT}/" "${STAGE_REPO_DIR}/"

cat >"${STAGE_DIR}/00-run.sh" <<'EOF'
#!/bin/bash -e

install -d "${ROOTFS_DIR}/opt"
cp -a files/opt/VibeSensor "${ROOTFS_DIR}/opt/"

on_chroot <<'CHROOT'
set -euxo pipefail
cd /opt/VibeSensor

export DEBIAN_FRONTEND=noninteractive
export VIBESENSOR_SKIP_SERVICE_START=1
./pi/scripts/install_pi.sh

install -m 0644 \
  /opt/VibeSensor/image/pi-gen/assets/vibesensor-hotspot.service \
  /etc/systemd/system/vibesensor-hotspot.service

mkdir -p /etc/systemd/system/multi-user.target.wants
ln -sf /etc/systemd/system/vibesensor.service \
  /etc/systemd/system/multi-user.target.wants/vibesensor.service
ln -sf /etc/systemd/system/vibesensor-hotspot.service \
  /etc/systemd/system/multi-user.target.wants/vibesensor-hotspot.service
CHROOT
EOF
chmod +x "${STAGE_DIR}/00-run.sh"

cat >"${PI_GEN_DIR}/config" <<'EOF'
# This image is tuned for Raspberry Pi 3 A+ deployments.
IMG_NAME='vibesensor-rpi3a-plus-bookworm-lite'
RELEASE='bookworm'
ENABLE_SSH=1
STAGE_LIST="stage0 stage1 stage2 stage-vibesensor"
EOF

(
  cd "${PI_GEN_DIR}"
  ./build-docker.sh
)

find "${PI_GEN_DIR}/deploy" -maxdepth 1 -type f \
  \( -name "*.img" -o -name "*.img.xz" -o -name "*.zip" -o -name "*.sha256" \) \
  -exec cp -f {} "${OUT_DIR}/" \;

if ! find "${OUT_DIR}" -maxdepth 1 -type f \( -name "*.img" -o -name "*.img.xz" -o -name "*.zip" \) | grep -q .; then
  echo "No image artifacts were copied to ${OUT_DIR}"
  exit 1
fi

echo "Image artifacts available in: ${OUT_DIR}"
