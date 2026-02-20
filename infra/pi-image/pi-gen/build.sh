#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
CACHE_DIR="${SCRIPT_DIR}/.cache"
PI_GEN_DIR="${CACHE_DIR}/pi-gen"
PI_GEN_REF="${PI_GEN_REF:-bookworm}"
STAGE_DIR="${PI_GEN_DIR}/stage-vibesensor"
STAGE_STEP_DIR="${STAGE_DIR}/00-vibesensor"
STAGE_REPO_DIR="${STAGE_STEP_DIR}/files/opt/VibeSensor"
OUT_DIR="${SCRIPT_DIR}/out"
IMG_SUFFIX_BASE="-vibesensor-lite"
VS_FIRST_USER_NAME="${VS_FIRST_USER_NAME:-pi}"
VS_FIRST_USER_PASS="${VS_FIRST_USER_PASS:-vibesensor}"
VS_WPA_COUNTRY="${VS_WPA_COUNTRY:-US}"
# Set CLEAN=1 to force a full rebuild from scratch (default: incremental, reuses stage0-2)
CLEAN="${CLEAN:-0}"

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
require_cmd qemu-arm-static

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not available for current user."
  echo "Start Docker and/or add your user to the docker group."
  exit 1
fi

mkdir -p "${CACHE_DIR}" "${OUT_DIR}"

if [ -z "${VS_FIRST_USER_NAME}" ] || [ -z "${VS_FIRST_USER_PASS}" ]; then
  echo "VS_FIRST_USER_NAME and VS_FIRST_USER_PASS must be non-empty to avoid first-boot user prompt."
  exit 1
fi

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

# Always start stage-vibesensor from a clean copy of stage2's rootfs so that
# incremental builds (with stage0/1/2 skipped) still produce a correct image.
rm -rf "${ROOTFS_DIR}"
copy_previous
EOF
chmod +x "${STAGE_DIR}/prerun.sh"

rsync -a --delete \
  --exclude ".git/" \
  --exclude ".venv/" \
  --exclude "__pycache__/" \
  --exclude "*.pyc" \
  --exclude "infra/pi-image/pi-gen/.cache/" \
  --exclude "infra/pi-image/pi-gen/out/" \
  "${REPO_ROOT}/" "${STAGE_REPO_DIR}/"

cat >"${STAGE_STEP_DIR}/00-run.sh" <<'EOF'
#!/bin/bash -e

install -d "${ROOTFS_DIR}/opt"
cp -a files/opt/VibeSensor "${ROOTFS_DIR}/opt/"

install -d "${ROOTFS_DIR}/etc/vibesensor"
install -d -o 1000 -g 1000 "${ROOTFS_DIR}/var/lib/vibesensor" "${ROOTFS_DIR}/var/log/vibesensor"
install -d "${ROOTFS_DIR}/var/log/wifi"
install -d "${ROOTFS_DIR}/etc/systemd/system"
install -d "${ROOTFS_DIR}/etc/NetworkManager/conf.d"
install -d "${ROOTFS_DIR}/etc/tmpfiles.d"
install -d "${ROOTFS_DIR}/etc/ssh/sshd_config.d"

# Build the Python virtualenv inside the ARM rootfs via QEMU chroot emulation.
on_chroot << CHROOT_EOF
set -e
python3 -m venv /opt/VibeSensor/apps/server/.venv
/opt/VibeSensor/apps/server/.venv/bin/pip install --upgrade pip --quiet
/opt/VibeSensor/apps/server/.venv/bin/pip install -e /opt/VibeSensor/apps/server --quiet
chown -R 1000:1000 /opt/VibeSensor/apps/server/.venv
CHROOT_EOF

cat >"${ROOTFS_DIR}/etc/NetworkManager/conf.d/99-vibesensor-dnsmasq.conf" <<'NMCONF'
[main]
dns=dnsmasq
NMCONF

install -m 0644 \
  "${ROOTFS_DIR}/opt/VibeSensor/infra/pi-image/pi-gen/assets/vibesensor-wifi.conf" \
  "${ROOTFS_DIR}/etc/tmpfiles.d/vibesensor-wifi.conf"

if [ ! -f "${ROOTFS_DIR}/etc/vibesensor/config.yaml" ]; then
  install -m 0644 \
    "${ROOTFS_DIR}/opt/VibeSensor/apps/server/config.example.yaml" \
    "${ROOTFS_DIR}/etc/vibesensor/config.yaml"
fi

if [ ! -f "${ROOTFS_DIR}/etc/vibesensor/wifi-secrets.env" ]; then
  install -m 0600 \
    "${ROOTFS_DIR}/opt/VibeSensor/apps/server/wifi-secrets.example.env" \
    "${ROOTFS_DIR}/etc/vibesensor/wifi-secrets.env"
fi

install -m 0644 \
  "${ROOTFS_DIR}/opt/VibeSensor/infra/pi-image/pi-gen/assets/vibesensor-hotspot.service" \
  "${ROOTFS_DIR}/etc/systemd/system/vibesensor-hotspot.service"

install -m 0644 \
  "${ROOTFS_DIR}/opt/VibeSensor/infra/pi-image/pi-gen/assets/vibesensor-rfkill-unblock.service" \
  "${ROOTFS_DIR}/etc/systemd/system/vibesensor-rfkill-unblock.service"

install -m 0644 \
  "${ROOTFS_DIR}/opt/VibeSensor/infra/pi-image/pi-gen/assets/vibesensor-hotspot-self-heal.service" \
  "${ROOTFS_DIR}/etc/systemd/system/vibesensor-hotspot-self-heal.service"

install -m 0644 \
  "${ROOTFS_DIR}/opt/VibeSensor/infra/pi-image/pi-gen/assets/vibesensor-hotspot-self-heal.timer" \
  "${ROOTFS_DIR}/etc/systemd/system/vibesensor-hotspot-self-heal.timer"

sed \
  -e 's#__PI_DIR__#/opt/VibeSensor/apps/server#g' \
  -e 's#__VENV_DIR__#/opt/VibeSensor/apps/server/.venv#g' \
  -e 's#__SERVICE_USER__#pi#g' \
  "${ROOTFS_DIR}/opt/VibeSensor/apps/server/systemd/vibesensor.service" >"${ROOTFS_DIR}/etc/systemd/system/vibesensor.service"

mkdir -p "${ROOTFS_DIR}/etc/systemd/system/multi-user.target.wants"
ln -sf /etc/systemd/system/vibesensor.service \
  "${ROOTFS_DIR}/etc/systemd/system/multi-user.target.wants/vibesensor.service"
ln -sf /etc/systemd/system/vibesensor-hotspot.service \
  "${ROOTFS_DIR}/etc/systemd/system/multi-user.target.wants/vibesensor-hotspot.service"
mkdir -p "${ROOTFS_DIR}/etc/systemd/system/NetworkManager.service.wants"
ln -sf /etc/systemd/system/vibesensor-rfkill-unblock.service \
  "${ROOTFS_DIR}/etc/systemd/system/NetworkManager.service.wants/vibesensor-rfkill-unblock.service"
mkdir -p "${ROOTFS_DIR}/etc/systemd/system/timers.target.wants"
ln -sf /etc/systemd/system/vibesensor-hotspot-self-heal.timer \
  "${ROOTFS_DIR}/etc/systemd/system/timers.target.wants/vibesensor-hotspot-self-heal.timer"

# Force password SSH auth for the first user so hotspot-only deployments can
# always recover the device without pre-provisioned SSH keys.
cat >"${ROOTFS_DIR}/etc/ssh/sshd_config.d/99-vibesensor-password-auth.conf" <<'SSHCONF'
PasswordAuthentication yes
KbdInteractiveAuthentication no
UsePAM yes
SSHCONF
EOF
chmod +x "${STAGE_STEP_DIR}/00-run.sh"

cat >"${STAGE_STEP_DIR}/00-packages" <<'EOF'
network-manager
dnsmasq
rfkill
iw
gpsd
gpsd-clients
python3-venv
python3-pip
libopenblas0-pthread
EOF

# Ensure this custom stage is exported as the final image artifact.
touch "${STAGE_DIR}/EXPORT_IMAGE"

# Avoid accidentally exporting stock stage2 images that could be flashed by mistake.
touch "${PI_GEN_DIR}/stage2/SKIP_IMAGES"

cat >"${PI_GEN_DIR}/config" <<EOF
# This image is tuned for Raspberry Pi 3 A+ deployments.
IMG_NAME='vibesensor-rpi3a-plus-bookworm-lite'
IMG_SUFFIX='${IMG_SUFFIX}'
RELEASE='bookworm'
FIRST_USER_NAME='${VS_FIRST_USER_NAME}'
FIRST_USER_PASS='${VS_FIRST_USER_PASS}'
DISABLE_FIRST_BOOT_USER_RENAME=1
WPA_COUNTRY='${VS_WPA_COUNTRY}'
ENABLE_SSH=1
PUBKEY_ONLY_SSH=0
STAGE_LIST="stage0 stage1 stage2 stage-vibesensor"
EOF

PREV_WORK_EXISTS=0
if docker ps -a --format '{{.Names}}' | grep -Fxq pigen_work; then
  PREV_WORK_EXISTS=1
fi

if [ "${CLEAN}" = "1" ] || [ "${PREV_WORK_EXISTS}" = "0" ]; then
  if [ "${PREV_WORK_EXISTS}" = "1" ]; then
    echo "CLEAN=1: removing previous pigen_work container"
    docker rm -v pigen_work >/dev/null
  fi
  rm -f "${PI_GEN_DIR}/stage0/SKIP" "${PI_GEN_DIR}/stage1/SKIP" "${PI_GEN_DIR}/stage2/SKIP"
  echo "Full build: rebuilding all stages"
else
  echo "Incremental build: skipping stage0/1/2 (set CLEAN=1 to rebuild from scratch)"
  touch "${PI_GEN_DIR}/stage0/SKIP"
  touch "${PI_GEN_DIR}/stage1/SKIP"
  touch "${PI_GEN_DIR}/stage2/SKIP"
fi

(
  cd "${PI_GEN_DIR}"
  # CONTINUE=1      — reuse existing pigen_work volumes (incremental) instead of aborting.
  # PRESERVE_CONTAINER=1 — don't rm pigen_work after the build so the next run can be incremental.
  CONTINUE=1 PRESERVE_CONTAINER=1 ./build-docker.sh
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

  candidate="$(find "${base_dir}" -maxdepth 1 -type f -name "*${IMG_SUFFIX}*.img" | sort -r | head -n 1 || true)"
  if [ -n "${candidate}" ]; then
    printf '%s\n' "${candidate}"
    return 0
  fi

  candidate="$(find "${base_dir}" -maxdepth 1 -type f -name "*${IMG_SUFFIX}*.img.xz" | sort -r | head -n 1 || true)"
  if [ -n "${candidate}" ]; then
    printf '%s\n' "${candidate}"
    return 0
  fi

  candidate="$(find "${base_dir}" -maxdepth 1 -type f -name "*${IMG_SUFFIX}*.zip" | sort -r | head -n 1 || true)"
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
    INSPECT_IMG="$(find "${INSPECT_DIR}" -maxdepth 1 -type f -name "*.img" | sort -r | head -n 1 || true)"
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

if [ ! -x "${ROOT_MNT}/usr/bin/nmcli" ]; then
  echo "Validation failed: missing executable ${ROOT_MNT}/usr/bin/nmcli"
  exit 1
fi

assert_rootfs_binary() {
  local name="$1"
  local path=""
  for candidate in "/usr/bin/${name}" "/usr/sbin/${name}" "/bin/${name}" "/sbin/${name}"; do
    if [ -x "${ROOT_MNT}${candidate}" ]; then
      path="${candidate}"
      break
    fi
  done
  if [ -z "${path}" ]; then
    echo "Validation failed: missing executable '${name}' in rootfs PATH locations"
    exit 1
  fi
  printf '%s\n' "${path}"
}

assert_rootfs_package() {
  local pkg="$1"
  if ! awk -v pkg="${pkg}" '
    BEGIN {in_pkg=0; ok=0}
    $0 == "Package: " pkg {in_pkg=1; next}
    /^Package: / && in_pkg {exit}
    in_pkg && $0 == "Status: install ok installed" {ok=1}
    END {exit(ok ? 0 : 1)}
  ' "${ROOT_MNT}/var/lib/dpkg/status"; then
    echo "Validation failed: package '${pkg}' is not installed in image rootfs"
    exit 1
  fi
}

RFKILL_PATH="$(assert_rootfs_binary rfkill)"
IW_PATH="$(assert_rootfs_binary iw)"
DNSMASQ_PATH="$(assert_rootfs_binary dnsmasq)"
GPSD_PATH="$(assert_rootfs_binary gpsd)"

if [ ! -f "${ROOT_MNT}/etc/systemd/system/vibesensor-hotspot.service" ]; then
  echo "Validation failed: missing ${ROOT_MNT}/etc/systemd/system/vibesensor-hotspot.service"
  exit 1
fi

if [ ! -f "${ROOT_MNT}/etc/systemd/system/vibesensor-rfkill-unblock.service" ]; then
  echo "Validation failed: missing ${ROOT_MNT}/etc/systemd/system/vibesensor-rfkill-unblock.service"
  exit 1
fi

if [ ! -d "${ROOT_MNT}/etc/vibesensor" ]; then
  echo "Validation failed: missing ${ROOT_MNT}/etc/vibesensor"
  exit 1
fi

if [ ! -d "${ROOT_MNT}/var/log/wifi" ] && [ ! -f "${ROOT_MNT}/etc/tmpfiles.d/vibesensor-wifi.conf" ]; then
  echo "Validation failed: missing /var/log/wifi and /etc/tmpfiles.d/vibesensor-wifi.conf"
  exit 1
fi

if [ ! -f "${ROOT_MNT}/opt/VibeSensor/apps/server/.venv/bin/python3" ] && \
   [ ! -f "${ROOT_MNT}/opt/VibeSensor/apps/server/.venv/bin/python" ]; then
  echo "Validation failed: Python venv not built at ${ROOT_MNT}/opt/VibeSensor/apps/server/.venv/bin"
  exit 1
fi

assert_rootfs_package gpsd
assert_rootfs_package gpsd-clients
assert_rootfs_package libopenblas0-pthread
assert_rootfs_package libgfortran5

OPENBLAS_LIB="$(find "${ROOT_MNT}/usr/lib" -type f -name 'libopenblas*.so*' | head -n 1 || true)"
if [ -z "${OPENBLAS_LIB}" ]; then
  echo "Validation failed: OpenBLAS runtime library not found in rootfs"
  exit 1
fi

run_qemu_chroot() {
  # Use qemu-arm-static for deterministic ARM-side validation from x86 host.
  sudo cp /usr/bin/qemu-arm-static "${ROOT_MNT}/usr/bin/"
  sudo chroot "${ROOT_MNT}" /usr/bin/qemu-arm-static "$@"
}

if ! run_qemu_chroot /opt/VibeSensor/apps/server/.venv/bin/python - <<'PY'
import importlib
mods = [
    "numpy",
    "yaml",
    "reportlab",
    "fastapi",
    "uvicorn",
    "vibesensor",
    "vibesensor_core",
    "vibesensor_shared",
    "vibesensor_adapters",
]
for mod in mods:
    importlib.import_module(mod)
print("IMPORT_VALIDATION_OK")
PY
then
  echo "Validation failed: Python import smoke test failed in ARM chroot"
  exit 1
fi

if ! run_qemu_chroot /bin/bash -lc '
set -e
export VIBESENSOR_DISABLE_AUTO_APP=1
set +e
timeout 10s /opt/VibeSensor/apps/server/.venv/bin/python -m vibesensor.app --config /etc/vibesensor/config.yaml >/tmp/vibesensor-smoke.log 2>&1
code=$?
set -e
if [ "$code" -ne 0 ] && [ "$code" -ne 124 ]; then
  echo "Server startup smoke command failed with code=${code}"
  tail -n 80 /tmp/vibesensor-smoke.log || true
  exit 1
fi
if ! grep -q "Application startup complete" /tmp/vibesensor-smoke.log; then
  echo "Server startup smoke did not reach successful startup"
  tail -n 80 /tmp/vibesensor-smoke.log || true
  exit 1
fi
echo "SERVER_STARTUP_SMOKE_OK"
'; then
  echo "Validation failed: vibesensor.app startup smoke failed in ARM chroot"
  exit 1
fi

if grep -n "apt-get" "${ROOT_MNT}/opt/VibeSensor/apps/server/scripts/hotspot_nmcli.sh" >/dev/null 2>&1; then
  echo "Validation failed: hotspot script still contains apt-get"
  exit 1
fi

if ! grep -n "/var/log/wifi" "${ROOT_MNT}/opt/VibeSensor/apps/server/scripts/hotspot_nmcli.sh" >/dev/null 2>&1; then
  echo "Validation failed: hotspot script does not reference /var/log/wifi"
  exit 1
fi

if [ ! -f "${ROOT_MNT}/etc/NetworkManager/conf.d/99-vibesensor-dnsmasq.conf" ]; then
  echo "Validation failed: missing ${ROOT_MNT}/etc/NetworkManager/conf.d/99-vibesensor-dnsmasq.conf"
  exit 1
fi

if [ -f "${ROOT_MNT}/etc/xdg/autostart/piwiz.desktop" ]; then
  echo "Validation failed: first-boot user wizard still present (${ROOT_MNT}/etc/xdg/autostart/piwiz.desktop)"
  exit 1
fi

if ! grep -E "^${VS_FIRST_USER_NAME}:" "${ROOT_MNT}/etc/passwd" >/dev/null 2>&1; then
  echo "Validation failed: expected user '${VS_FIRST_USER_NAME}' missing from /etc/passwd"
  exit 1
fi

if [ ! -f "${ROOT_MNT}/etc/ssh/sshd_config.d/99-vibesensor-password-auth.conf" ]; then
  echo "Validation failed: missing SSH password-auth drop-in"
  exit 1
fi

if ! grep -Eq '^PasswordAuthentication[[:space:]]+yes$' "${ROOT_MNT}/etc/ssh/sshd_config.d/99-vibesensor-password-auth.conf"; then
  echo "Validation failed: SSH password auth drop-in does not enable PasswordAuthentication"
  exit 1
fi

SHADOW_LINE="$(sudo grep -E "^${VS_FIRST_USER_NAME}:" "${ROOT_MNT}/etc/shadow" || true)"
SHADOW_HASH="$(printf '%s\n' "${SHADOW_LINE}" | cut -d: -f2)"
if [ -z "${SHADOW_HASH}" ] || [ "${SHADOW_HASH}" = "*" ] || [ "${SHADOW_HASH}" = "!" ]; then
  echo "Validation failed: first user '${VS_FIRST_USER_NAME}' has no usable password hash"
  exit 1
fi

if ! python3 - "${VS_FIRST_USER_PASS}" "${SHADOW_HASH}" <<'PY'
import crypt
import sys
plain = sys.argv[1]
shadow_hash = sys.argv[2]
sys.exit(0 if crypt.crypt(plain, shadow_hash) == shadow_hash else 1)
PY
then
  echo "Validation failed: first user password hash does not match VS_FIRST_USER_PASS"
  exit 1
fi

echo "=== Validation: /opt/VibeSensor exists ==="
ls -la "${ROOT_MNT}/opt/VibeSensor" | head -n 20

echo "=== Validation: nmcli + rfkill + iw + dnsmasq binaries ==="
ls -l "${ROOT_MNT}/usr/bin/nmcli" "${ROOT_MNT}${RFKILL_PATH}" "${ROOT_MNT}${IW_PATH}" "${ROOT_MNT}${DNSMASQ_PATH}" "${ROOT_MNT}${GPSD_PATH}"

echo "=== Validation: vibesensor systemd units ==="
ls -la "${ROOT_MNT}/etc/systemd/system" | grep -i vibesensor || true

echo "=== Validation: first user preconfigured, wizard disabled ==="
grep -n "^${VS_FIRST_USER_NAME}:" "${ROOT_MNT}/etc/passwd"
if [ -f "${ROOT_MNT}/etc/xdg/autostart/piwiz.desktop" ]; then
  echo "ERROR: piwiz.desktop present"
  exit 1
else
  echo "OK: piwiz.desktop absent"
fi

echo "=== Validation: /etc/vibesensor ==="
ls -la "${ROOT_MNT}/etc/vibesensor"

echo "=== Validation: SSH auth configuration ==="
cat "${ROOT_MNT}/etc/ssh/sshd_config.d/99-vibesensor-password-auth.conf"

echo "=== Validation: /var/log/wifi or tmpfiles ==="
if [ -d "${ROOT_MNT}/var/log/wifi" ]; then
  ls -ld "${ROOT_MNT}/var/log/wifi"
fi
if [ -f "${ROOT_MNT}/etc/tmpfiles.d/vibesensor-wifi.conf" ]; then
  cat "${ROOT_MNT}/etc/tmpfiles.d/vibesensor-wifi.conf"
fi

echo "=== Validation: NetworkManager conf.d drop-in ==="
cat "${ROOT_MNT}/etc/NetworkManager/conf.d/99-vibesensor-dnsmasq.conf"

echo "=== Validation: Python venv ==="
ls -la "${ROOT_MNT}/opt/VibeSensor/apps/server/.venv/bin/python"* || true

echo "=== Validation: OpenBLAS runtime ==="
echo "${OPENBLAS_LIB}"

echo "=== Validation: hotspot script has no apt-get ==="
if grep -n "apt-get" "${ROOT_MNT}/opt/VibeSensor/apps/server/scripts/hotspot_nmcli.sh"; then
  echo "ERROR: found apt-get in hotspot script"
  exit 1
else
  echo "OK: no apt-get found"
fi

echo "=== Validation: hotspot script references /var/log/wifi ==="
grep -n "/var/log/wifi" "${ROOT_MNT}/opt/VibeSensor/apps/server/scripts/hotspot_nmcli.sh"

cleanup_mounts
trap - EXIT

mkdir -p /mnt/c/temp
cp -f "${FINAL_ARTIFACT}" /mnt/c/temp/
if [ -f "${INSPECT_IMG}" ]; then
  cp -f "${INSPECT_IMG}" /mnt/c/temp/
fi

echo "Image artifacts available in: ${OUT_DIR}"
echo "Final artifact: ${FINAL_ARTIFACT}"
if [ -f "${INSPECT_IMG}" ]; then
  echo "Inspection image: ${INSPECT_IMG}"
fi
echo "Copied artifact to: /mnt/c/temp/$(basename "${FINAL_ARTIFACT}")"
