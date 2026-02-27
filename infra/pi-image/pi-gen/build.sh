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
APP_ARTIFACT_DIR="${OUT_DIR}/app-artifacts"
APP_WHEEL_DIR="${APP_ARTIFACT_DIR}/wheels"
APP_PUBLIC_DIR="${APP_ARTIFACT_DIR}/public"
IMG_SUFFIX_BASE="-vibesensor-lite"
BUILD_MODE="${BUILD_MODE:-all}"
VS_FIRST_USER_NAME="${VS_FIRST_USER_NAME:-pi}"
VS_FIRST_USER_PASS="${VS_FIRST_USER_PASS:-vibesensor}"
VS_WPA_COUNTRY="${VS_WPA_COUNTRY:-US}"
SSH_FIRST_BOOT_DEBUG="${SSH_FIRST_BOOT_DEBUG:-0}"
VALIDATE="${VALIDATE:-1}"
FAST="${FAST:-0}"
FORCE_UI_BUILD="${FORCE_UI_BUILD:-0}"
COPY_ARTIFACT_DIR="${COPY_ARTIFACT_DIR:-}"
UI_HASH_FILE="${CACHE_DIR}/ui-build.hash"
# Set CLEAN=1 to force a full rebuild from scratch (default: incremental, reuses stage0-2)
CLEAN="${CLEAN:-0}"
RASPBIAN_MIRROR="${RASPBIAN_MIRROR:-}"
RASPBIAN_MIRROR_FALLBACKS=(
  "http://raspbian.raspberrypi.com/raspbian/"
  "http://mirror.init7.net/raspbian/raspbian/"
  "http://mirrors.ustc.edu.cn/raspbian/raspbian/"
  "http://ftp.halifax.rwth-aachen.de/raspbian/raspbian/"
  "http://mirror.ox.ac.uk/sites/archive.raspbian.org/archive/raspbian/"
)

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

if [[ "${BUILD_MODE}" != "all" && "${BUILD_MODE}" != "app" && "${BUILD_MODE}" != "image" ]]; then
  echo "Invalid BUILD_MODE='${BUILD_MODE}'. Use one of: all, app, image."
  exit 1
fi

require_app_prereqs() {
  require_cmd git
  require_cmd rsync
  require_cmd npm
  require_cmd python3
}

require_image_prereqs() {
  require_cmd git
  require_cmd docker
  require_cmd rsync
  require_cmd sudo
  require_cmd curl
  require_cmd losetup
  require_cmd mount
  require_cmd umount
  require_cmd awk
  require_cmd qemu-arm-static
}

mkdir -p "${CACHE_DIR}" "${OUT_DIR}" "${APP_WHEEL_DIR}"

if [[ "${BUILD_MODE}" == "app" || "${BUILD_MODE}" == "all" ]]; then
  require_app_prereqs
fi

if [[ "${BUILD_MODE}" == "image" || "${BUILD_MODE}" == "all" ]]; then
  require_image_prereqs
  if ! docker info >/dev/null 2>&1; then
    echo "Docker daemon is not available for current user."
    echo "Start Docker and/or add your user to the docker group."
    exit 1
  fi
fi

if [ "${FAST}" = "1" ]; then
  VALIDATE=0
fi

normalize_mirror() {
  local value="$1"
  value="${value%/}/"
  printf '%s\n' "${value}"
}

mirror_release_url() {
  local base="$1"
  printf '%sdists/%s/Release\n' "$(normalize_mirror "${base}")" "${PI_GEN_REF}"
}

probe_mirror() {
  local base="$1"
  local release_url
  release_url="$(mirror_release_url "${base}")"
  curl -fsI --max-time 10 "${release_url}" >/dev/null 2>&1
}

select_raspbian_mirror() {
  local candidate=""
  if [ -n "${RASPBIAN_MIRROR}" ]; then
    candidate="$(normalize_mirror "${RASPBIAN_MIRROR}")"
    if ! probe_mirror "${candidate}"; then
      echo "Configured RASPBIAN_MIRROR is unreachable: ${candidate}"
      exit 1
    fi
    printf '%s\n' "${candidate}"
    return 0
  fi

  for candidate in "${RASPBIAN_MIRROR_FALLBACKS[@]}"; do
    if probe_mirror "${candidate}"; then
      printf '%s\n' "$(normalize_mirror "${candidate}")"
      return 0
    fi
  done
  echo "No reachable Raspbian mirror found."
  exit 1
}

if [[ "${BUILD_MODE}" == "image" || "${BUILD_MODE}" == "all" ]]; then
  RASPBIAN_MIRROR="$(select_raspbian_mirror)"
  echo "Using Raspbian mirror: ${RASPBIAN_MIRROR}"
fi

compute_ui_hash() {
  (
    cd "${REPO_ROOT}"
    git ls-files \
      apps/ui \
      libs/shared/contracts \
      tools/config/sync_shared_contracts_to_ui.mjs \
      | LC_ALL=C sort \
      | xargs sha256sum \
      | sha256sum \
      | awk '{print $1}'
  )
}

build_ui_bundle() {
  local ui_dir="${REPO_ROOT}/apps/ui"
  local server_public_dir="${REPO_ROOT}/apps/server/public"
  local should_build="1"
  local current_hash=""
  local previous_hash=""

  if [ "${FORCE_UI_BUILD}" != "1" ] && [ -d "${ui_dir}/dist" ]; then
    current_hash="$(compute_ui_hash || true)"
    if [ -f "${UI_HASH_FILE}" ]; then
      previous_hash="$(cat "${UI_HASH_FILE}")"
    fi
    if [ -n "${current_hash}" ] && [ "${current_hash}" = "${previous_hash}" ]; then
      should_build="0"
      echo "UI sources unchanged; skipping npm run build"
    fi
  fi

  if [ ! -d "${ui_dir}/node_modules" ]; then
    echo "UI dependencies missing; running npm ci in apps/ui"
    (cd "${ui_dir}" && npm ci)
  fi

  if [ "${should_build}" = "1" ]; then
    echo "Building UI bundle"
    (cd "${ui_dir}" && npm run build)
    if [ -z "${current_hash}" ]; then
      current_hash="$(compute_ui_hash || true)"
    fi
    if [ -n "${current_hash}" ]; then
      printf '%s\n' "${current_hash}" >"${UI_HASH_FILE}"
    fi
  fi

  echo "Syncing UI bundle into apps/server/public"
  mkdir -p "${server_public_dir}"
  rsync -a --delete "${ui_dir}/dist/" "${server_public_dir}/"
}

build_app_artifacts() {
  local build_root=""
  local wheel_path=""

  echo "Preparing app artifacts..."
  build_ui_bundle

  rm -rf "${APP_ARTIFACT_DIR}"
  mkdir -p "${APP_WHEEL_DIR}" "${APP_PUBLIC_DIR}"
  rsync -a --delete "${REPO_ROOT}/apps/server/public/" "${APP_PUBLIC_DIR}/"

  build_root="$(mktemp -d -p "${CACHE_DIR}" app-build-XXXXXX)"
  mkdir -p \
    "${build_root}/apps" \
    "${build_root}/libs/core" \
    "${build_root}/libs/shared" \
    "${build_root}/tools"
  rsync -a --delete \
    "${REPO_ROOT}/apps/server/" "${build_root}/apps/server/"
  rsync -a --delete \
    "${REPO_ROOT}/apps/simulator/" "${build_root}/apps/simulator/"
  rsync -a --delete \
    "${REPO_ROOT}/libs/core/python/" "${build_root}/libs/core/python/"
  rsync -a --delete \
    "${REPO_ROOT}/libs/shared/python/" "${build_root}/libs/shared/python/"
  rsync -a --delete \
    "${REPO_ROOT}/tools/config/" "${build_root}/tools/config/"

  rm -rf "${build_root}/apps/server/vibesensor/static"
  mkdir -p "${build_root}/apps/server/vibesensor/static"
  rsync -a --delete "${APP_PUBLIC_DIR}/" "${build_root}/apps/server/vibesensor/static/"

  (
    cd "${build_root}"
    python3 -m venv .build-venv
    ./.build-venv/bin/pip install --upgrade pip build >/dev/null
    ./.build-venv/bin/python -m build --wheel apps/server
  )

  wheel_path="$(find "${build_root}/apps/server/dist" -maxdepth 1 -type f -name 'vibesensor-*.whl' | sort -V | tail -n 1)"
  if [ -z "${wheel_path}" ]; then
    echo "Failed to build vibesensor wheel artifact."
    rm -rf "${build_root}"
    exit 1
  fi
  cp -f "${wheel_path}" "${APP_WHEEL_DIR}/"

  {
    echo "build_mode=app"
    echo "generated_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "wheel=$(basename "${wheel_path}")"
    echo "wheel_sha256=$(sha256sum "${APP_WHEEL_DIR}/$(basename "${wheel_path}")" | awk '{print $1}')"
  } >"${APP_ARTIFACT_DIR}/manifest.txt"

  rm -rf "${build_root}"
  echo "App artifacts ready in: ${APP_ARTIFACT_DIR}"
}

if [[ "${BUILD_MODE}" == "app" || "${BUILD_MODE}" == "all" ]]; then
  build_app_artifacts
fi

if [[ "${BUILD_MODE}" == "app" ]]; then
  echo "Build mode 'app' complete."
  exit 0
fi

APP_WHEEL_PATH="$(find "${APP_WHEEL_DIR}" -maxdepth 1 -type f -name 'vibesensor-*.whl' | sort -V | tail -n 1)"
if [ -z "${APP_WHEEL_PATH}" ]; then
  echo "Missing app wheel artifact in ${APP_WHEEL_DIR}."
  echo "Run BUILD_MODE=app ./infra/pi-image/pi-gen/build.sh first."
  exit 1
fi
APP_WHEEL_FILE="$(basename "${APP_WHEEL_PATH}")"
if [ ! -f "${APP_PUBLIC_DIR}/index.html" ]; then
  echo "Missing prebuilt UI assets in ${APP_PUBLIC_DIR}."
  echo "Run BUILD_MODE=app ./infra/pi-image/pi-gen/build.sh first."
  exit 1
fi

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

# pi-gen contains multiple hardcoded Raspbian source definitions (debootstrap,
# apt sources templates, and export-time source regeneration). Rewrite all to
# the selected reachable mirror.
while IFS= read -r mirror_file; do
  sed -i \
    -E "s#http://raspbian\\.raspberrypi\\.com/raspbian/#${RASPBIAN_MIRROR}#g" \
    "${mirror_file}"
done < <(rg -l "http://raspbian\\.raspberrypi\\.com/raspbian/" "${PI_GEN_DIR}")

rm -rf "${STAGE_DIR}"
mkdir -p "${STAGE_REPO_DIR}"

cat >"${STAGE_DIR}/prerun.sh" <<'EOF'
#!/bin/bash -e

# Always start stage-vibesensor from a clean copy of stage2's rootfs so that
# incremental builds (with stage0/1/2 skipped) still produce a correct image.
rm -rf "${ROOTFS_DIR}"
copy_previous

# Retarget stale apt source entries in reused rootfs snapshots when upstream
# mirrors are unavailable.
if [ -d "${ROOTFS_DIR}/etc/apt" ]; then
  find "${ROOTFS_DIR}/etc/apt" -type f \( -name '*.list' -o -name '*.sources' \) -print0 \
    | xargs -0 -r sed -i 's#http://raspbian.raspberrypi.com/raspbian/#__RASPBIAN_MIRROR__#g'
fi
EOF
chmod +x "${STAGE_DIR}/prerun.sh"
sed -i "s#__RASPBIAN_MIRROR__#${RASPBIAN_MIRROR}#g" "${STAGE_DIR}/prerun.sh"

rsync -a --delete \
  --exclude ".git/" \
  --exclude ".github/" \
  --exclude ".githooks/" \
  --exclude ".venv/" \
  --exclude ".pytest_cache/" \
  --exclude ".ruff_cache/" \
  --exclude ".mypy_cache/" \
  --exclude ".cache/" \
  --exclude "__pycache__/" \
  --exclude "*.pyc" \
  --exclude "artifacts/" \
  --exclude '$MNT/' \
  --exclude "apps/ui/" \
  --exclude "apps/simulator/" \
  --exclude "apps/server/tests/" \
  --exclude "apps/server/tests_e2e/" \
  --exclude "docs/" \
  --exclude "examples/" \
  --exclude "firmware/" \
  --exclude "hardware/" \
  --exclude "tools/tests/" \
  --include "apps/server/data/" \
  --include "apps/server/data/car_library.json" \
  --include "apps/server/data/report_i18n.json" \
  --exclude "apps/server/data/*" \
  --exclude "infra/pi-image/pi-gen/.cache/" \
  --exclude "infra/pi-image/pi-gen/.pip-cache-stage/" \
  --exclude "infra/pi-image/pi-gen/out/" \
  "${REPO_ROOT}/" "${STAGE_REPO_DIR}/"

mkdir -p "${STAGE_REPO_DIR}/apps/server/public"
rsync -a --delete "${APP_PUBLIC_DIR}/" "${STAGE_REPO_DIR}/apps/server/public/"

mkdir -p "${STAGE_STEP_DIR}/files/opt/vibesensor-artifacts/wheels"
cp -f "${APP_WHEEL_PATH}" "${STAGE_STEP_DIR}/files/opt/vibesensor-artifacts/wheels/${APP_WHEEL_FILE}"

cat >"${STAGE_STEP_DIR}/00-run.sh" <<'EOF'
#!/bin/bash -e

install -d "${ROOTFS_DIR}/opt"
cp -a files/opt/. "${ROOTFS_DIR}/opt/"

install -d "${ROOTFS_DIR}/etc/vibesensor"
install -d -o 1000 -g 1000 "${ROOTFS_DIR}/var/lib/vibesensor" "${ROOTFS_DIR}/var/log/vibesensor"
install -d "${ROOTFS_DIR}/var/log/wifi"
install -d "${ROOTFS_DIR}/etc/systemd/system"
install -d "${ROOTFS_DIR}/etc/NetworkManager/conf.d"
install -d "${ROOTFS_DIR}/etc/tmpfiles.d"
install -d "${ROOTFS_DIR}/etc/ssh/sshd_config.d"
install -d "${ROOTFS_DIR}/etc/systemd/system/ssh.service.d"
install -d "${ROOTFS_DIR}/etc/sudoers.d"
# Updater runs as pi and uses a restricted sudo wrapper for privileged ops.
cat >"${ROOTFS_DIR}/etc/sudoers.d/vibesensor-update" <<'SUDOERS'
pi ALL=(root) NOPASSWD: /opt/VibeSensor/apps/server/scripts/vibesensor_update_sudo.sh
SUDOERS
chmod 0440 "${ROOTFS_DIR}/etc/sudoers.d/vibesensor-update"

# Build the Python virtualenv inside the ARM rootfs via QEMU chroot emulation.
on_chroot << 'CHROOT_EOF'
set -e
PIP_TMP_CACHE=/tmp/vibesensor-pip-cache
WHEELHOUSE=/tmp/vibesensor-wheelhouse
PREBUILT_WHEEL="/opt/vibesensor-artifacts/wheels/__APP_WHEEL_FILE__"
BUILD_DEPS=(python3-dev)

if [ ! -f "${PREBUILT_WHEEL}" ]; then
  echo "ERROR: missing prebuilt app wheel at ${PREBUILT_WHEEL}"
  exit 1
fi

echo "Installing transient build deps for wheel compilation"
apt-get update
apt-get install -y --no-install-recommends "${BUILD_DEPS[@]}"

echo "Rebuilding ARM wheelhouse (wheel-first runtime)"
rm -rf "${WHEELHOUSE}"
mkdir -p "${WHEELHOUSE}"
mkdir -p "${PIP_TMP_CACHE}"
python3 -m venv /tmp/vibesensor-wheel-build
/tmp/vibesensor-wheel-build/bin/pip install --upgrade pip --quiet
/tmp/vibesensor-wheel-build/bin/pip wheel --wheel-dir "${WHEELHOUSE}" \
  --prefer-binary \
  --cache-dir "${PIP_TMP_CACHE}" \
  "${PREBUILT_WHEEL}"
/tmp/vibesensor-wheel-build/bin/pip wheel --wheel-dir "${WHEELHOUSE}" \
  --prefer-binary \
  --cache-dir "${PIP_TMP_CACHE}" \
  "setuptools>=68" \
  "wheel>=0.38"
rm -rf /tmp/vibesensor-wheel-build

python3 -m venv /opt/VibeSensor/apps/server/.venv
/opt/VibeSensor/apps/server/.venv/bin/pip install --upgrade pip --quiet
/opt/VibeSensor/apps/server/.venv/bin/pip install \
  --no-index \
  --find-links "${WHEELHOUSE}" \
  "setuptools>=68" \
  "wheel>=0.38" \
  --quiet
VIBESENSOR_WHEEL="$(find "${WHEELHOUSE}" -maxdepth 1 -type f -name 'vibesensor-*.whl' | sort -V | tail -n 1)"
if [ -z "${VIBESENSOR_WHEEL}" ]; then
  echo "ERROR: no vibesensor wheel found in ${WHEELHOUSE}"
  exit 1
fi
/opt/VibeSensor/apps/server/.venv/bin/pip install \
  --no-index \
  --find-links "${WHEELHOUSE}" \
  --force-reinstall \
  --no-build-isolation \
  "${VIBESENSOR_WHEEL}" \
  --quiet
echo "Purging transient build deps"
apt-get purge -y "${BUILD_DEPS[@]}"
apt-get autoremove -y --purge

# Trim image-only bloat that is not needed on Raspberry Pi 3 A+ runtime:
# - non-Broadcom firmware families,
# - kernel header packages (dev-only).
TRIM_PACKAGES=(
  firmware-atheros
  firmware-libertas
  firmware-mediatek
  firmware-realtek
  gpsd-tools
  build-essential
  gcc
  g++
  cpp
  gdb
  libc6-dbg
  manpages-dev
  mkvtoolnix
  iso-codes
  p7zip-full
)
while IFS= read -r pkg; do
  if [ -n "${pkg}" ]; then
    TRIM_PACKAGES+=("${pkg}")
  fi
done < <(dpkg-query -W -f='${Package}\n' 'linux-headers-*' 2>/dev/null || true)
INSTALLED_TRIM_PACKAGES=()
for pkg in "${TRIM_PACKAGES[@]}"; do
  if dpkg-query -W -f='${Status}' "${pkg}" 2>/dev/null | grep -q "install ok installed"; then
    INSTALLED_TRIM_PACKAGES+=("${pkg}")
  fi
done
if [ "${#INSTALLED_TRIM_PACKAGES[@]}" -gt 0 ]; then
  echo "Purging trim-only packages: ${INSTALLED_TRIM_PACKAGES[*]}"
  apt-get purge -y --auto-remove "${INSTALLED_TRIM_PACKAGES[@]}"
fi
SITE_PACKAGES="$(/opt/VibeSensor/apps/server/.venv/bin/python - <<'PY'
import site
print(site.getsitepackages()[0])
PY
)"
rm -rf "${SITE_PACKAGES}/data" "${SITE_PACKAGES}/public"
cp -a /opt/VibeSensor/apps/server/data "${SITE_PACKAGES}/data"
cp -a /opt/VibeSensor/apps/server/public "${SITE_PACKAGES}/public"
# Keep runtime assets/scripts/config while ensuring Python code comes from wheels.
rm -rf \
  /opt/VibeSensor/apps/server/vibesensor \
  /opt/VibeSensor/apps/server/tests \
  /opt/VibeSensor/apps/server/tests_e2e \
  "${WHEELHOUSE}" \
  "${PIP_TMP_CACHE}" \
  /opt/vibesensor-artifacts \
  '/opt/VibeSensor/$MNT' \
  /opt/VibeSensor/.git \
  /opt/VibeSensor/.github \
  /opt/VibeSensor/infra/pi-image/pi-gen/.pip-cache-stage
# Strip docs/manpages/locales from the appliance image to reduce size.
rm -rf /usr/share/doc/* /usr/share/man/* /usr/share/info/* /usr/share/lintian/* /usr/share/linda/*
find /usr/share/locale -mindepth 1 -maxdepth 1 \
  ! -name 'en*' \
  ! -name 'C' \
  ! -name 'POSIX' \
  ! -name 'locale.alias' \
  -exec rm -rf {} +
rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* /var/cache/apt/archives/partial/*
install -d -o 1000 -g 1000 /var/lib/vibesensor/firmware
# Embed baseline ESP firmware bundle from the latest GitHub Release.
# This enables first-boot flashing without running the updater.
cat >/tmp/vibesensor-fw-baseline.sh <<'FW_BASELINE_EOF'
#!/bin/bash
set -euo pipefail

VENV_PYTHON="/opt/VibeSensor/apps/server/.venv/bin/python"
VENV_FW_REFRESH="/opt/VibeSensor/apps/server/.venv/bin/vibesensor-fw-refresh"
FW_CACHE_DIR="/var/lib/vibesensor/firmware"

echo "Refreshing ESP firmware cache (embedding baseline)..."
"${VENV_FW_REFRESH}" \
  --cache-dir "${FW_CACHE_DIR}" 2>&1 || true

# If refresh succeeded, copy the downloaded cache as the baseline
if [ -d "${FW_CACHE_DIR}/current" ] && [ -f "${FW_CACHE_DIR}/current/flash.json" ]; then
  rm -rf "${FW_CACHE_DIR}/baseline"
  cp -a "${FW_CACHE_DIR}/current" "${FW_CACHE_DIR}/baseline"
  # Update source in baseline metadata
  if [ -f "${FW_CACHE_DIR}/baseline/_meta.json" ]; then
    "${VENV_PYTHON}" -c "
import json, pathlib
p = pathlib.Path('${FW_CACHE_DIR}/baseline/_meta.json')
d = json.loads(p.read_text())
d['source'] = 'baseline'
p.write_text(json.dumps(d, indent=2) + '\n')
"
  fi
  echo "Baseline firmware embedded successfully."
else
  echo "WARNING: Could not embed baseline firmware (no release found or network unavailable)."
  echo "First-boot flashing will require running the updater while online."
fi
FW_BASELINE_EOF
chown 1000:1000 /tmp/vibesensor-fw-baseline.sh
chmod +x /tmp/vibesensor-fw-baseline.sh
su - pi -c '/tmp/vibesensor-fw-baseline.sh'
rm -f /tmp/vibesensor-fw-baseline.sh
chown -R 1000:1000 /var/lib/vibesensor
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

# Ensure first-boot config paths are writable by the non-root service user and
# default HTTP binds to a non-privileged port.
sed -i \
  -e 's#state_file: data/hotspot-self-heal-state.json#state_file: /var/lib/vibesensor/hotspot-self-heal-state.json#' \
  -e 's#metrics_log_path: data/metrics.jsonl#metrics_log_path: /var/log/vibesensor/metrics.jsonl#' \
  -e 's#history_db_path: data/history.db#history_db_path: /var/lib/vibesensor/history.db#' \
  "${ROOTFS_DIR}/etc/vibesensor/config.yaml"

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

# Make first-boot SSH deterministic when host keys are intentionally absent in
# the baked image; generate device-unique keys before sshd starts.
cat >"${ROOTFS_DIR}/etc/systemd/system/ssh.service.d/10-vibesensor-hostkeys.conf" <<'SSHUNIT'
[Unit]
Wants=regenerate_ssh_host_keys.service
After=regenerate_ssh_host_keys.service

[Service]
ExecStartPre=/bin/sh -c 'if ! ls /etc/ssh/ssh_host_*_key >/dev/null 2>&1; then /usr/bin/ssh-keygen -A; fi'
SSHUNIT

if [ "__SSH_FIRST_BOOT_DEBUG__" = "1" ]; then
  install -d "${ROOTFS_DIR}/usr/local/sbin"
  cat >"${ROOTFS_DIR}/usr/local/sbin/vibesensor-ssh-debug" <<'SSHDEBUG'
#!/bin/sh
set -eu

FWLOC=""
if FWLOC="$(/usr/lib/raspberrypi-sys-mods/get_fw_loc 2>/dev/null)"; then
  :
elif [ -d /boot/firmware ]; then
  FWLOC=/boot/firmware
else
  FWLOC=/boot
fi

OUT="${FWLOC}/ssh-debug.txt"

{
  echo "=== vibesensor ssh debug ($(date -u +%Y-%m-%dT%H:%M:%SZ)) ==="
  echo "-- ssh service status --"
  systemctl --no-pager --full status ssh || true
  echo
  echo "-- regenerate_ssh_host_keys service status --"
  systemctl --no-pager --full status regenerate_ssh_host_keys || true
  echo
  echo "-- last boot journal (ssh units) --"
  journalctl -b --no-pager -u regenerate_ssh_host_keys -u ssh || true
  echo
  echo "-- host key files --"
  ls -la /etc/ssh/ssh_host_* || true
} >"${OUT}" 2>&1
SSHDEBUG
  chmod 0755 "${ROOTFS_DIR}/usr/local/sbin/vibesensor-ssh-debug"

  cat >"${ROOTFS_DIR}/etc/systemd/system/vibesensor-ssh-debug.service" <<'SSHDEBUGUNIT'
[Unit]
Description=Write first-boot SSH diagnostics to firmware partition
After=multi-user.target
Wants=ssh.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/vibesensor-ssh-debug

[Install]
WantedBy=multi-user.target
SSHDEBUGUNIT

  ln -sf /etc/systemd/system/vibesensor-ssh-debug.service \
    "${ROOTFS_DIR}/etc/systemd/system/multi-user.target.wants/vibesensor-ssh-debug.service"
fi
EOF
chmod +x "${STAGE_STEP_DIR}/00-run.sh"
sed -i "s#__APP_WHEEL_FILE__#${APP_WHEEL_FILE}#g" "${STAGE_STEP_DIR}/00-run.sh"
sed -i "s/__SSH_FIRST_BOOT_DEBUG__/${SSH_FIRST_BOOT_DEBUG}/g" "${STAGE_STEP_DIR}/00-run.sh"

cat >"${STAGE_STEP_DIR}/00-packages" <<'EOF'
network-manager
dnsmasq
rfkill
iw
gpsd
python3-venv
libopenblas0-pthread
libopenjp2-7
EOF

# Ensure this custom stage is exported as the final image artifact.
touch "${STAGE_DIR}/EXPORT_IMAGE"

# Avoid accidentally exporting stock stage2 images that could be flashed by mistake.
touch "${PI_GEN_DIR}/stage2/SKIP_IMAGES"

# Trim apt metadata after export-image source rewrites so it doesn't inflate
# final image size.
EXPORT_TRIM_DIR="${PI_GEN_DIR}/export-image/04-vibesensor-trim"
mkdir -p "${EXPORT_TRIM_DIR}"
cat >"${EXPORT_TRIM_DIR}/00-run.sh" <<'EOF'
#!/bin/bash -e

on_chroot << 'CHROOT_EOF'
set -e
rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* /var/cache/apt/archives/partial/*
CHROOT_EOF
EOF
chmod +x "${EXPORT_TRIM_DIR}/00-run.sh"

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

  candidate="$(find "${base_dir}" -maxdepth 1 -type f -name "image_*${IMG_SUFFIX}*.img" | sort -r | head -n 1 || true)"
  if [ -n "${candidate}" ]; then
    printf '%s\n' "${candidate}"
    return 0
  fi

  candidate="$(find "${base_dir}" -maxdepth 1 -type f -name "image_*${IMG_SUFFIX}*.img.xz" | sort -r | head -n 1 || true)"
  if [ -n "${candidate}" ]; then
    printf '%s\n' "${candidate}"
    return 0
  fi

  candidate="$(find "${base_dir}" -maxdepth 1 -type f -name "image_*${IMG_SUFFIX}*.zip" | sort -r | head -n 1 || true)"
  if [ -n "${candidate}" ]; then
    printf '%s\n' "${candidate}"
    return 0
  fi

  # Backward-compatible fallback: ignore legacy latest* aliases if they exist.
  candidate="$(find "${base_dir}" -maxdepth 1 -type f -name "*${IMG_SUFFIX}*.zip" ! -name "latest${IMG_SUFFIX}.*" | sort -r | head -n 1 || true)"
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

BUILD_GIT_SHA="$(git -C "${REPO_ROOT}" rev-parse --short=12 HEAD)"
BUILD_GIT_BRANCH="$(git -C "${REPO_ROOT}" rev-parse --abbrev-ref HEAD)"
BUILD_TIME_UTC="$(date -u +%Y%m%dT%H%M%SZ)"
FINAL_BASENAME="$(basename "${FINAL_ARTIFACT}")"
VERSION_INFO_FILE="${OUT_DIR}/${FINAL_BASENAME}.version.txt"
FINAL_ARTIFACT_SHA256="${FINAL_ARTIFACT}.sha256"

prune_old_artifacts() {
  local base_dir="$1"
  local keep_file="$2"
  local keep_version_info="$3"
  local keep_sha256="$4"
  local path=""

  while IFS= read -r path; do
    case "${path}" in
      "${keep_file}"|"${keep_version_info}"|"${keep_sha256}")
        continue
        ;;
    esac
    rm -f "${path}"
  done < <(
    find "${base_dir}" -maxdepth 1 -type f \
      \( -name "*${IMG_SUFFIX}*.img" -o -name "*${IMG_SUFFIX}*.img.xz" -o -name "*${IMG_SUFFIX}*.zip" -o -name "*${IMG_SUFFIX}*.sha256" -o -name "*${IMG_SUFFIX}*.version.txt" \) \
      | sort
  )
}

INSPECT_DIR="${OUT_DIR}/inspect"
mkdir -p "${INSPECT_DIR}"
INSPECT_IMG="${FINAL_ARTIFACT}"

if [ "${VALIDATE}" = "1" ]; then
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

  if [ ! -f "${ROOT_MNT}/etc/systemd/system/vibesensor-hotspot-self-heal.service" ]; then
    echo "Validation failed: missing ${ROOT_MNT}/etc/systemd/system/vibesensor-hotspot-self-heal.service"
    exit 1
  fi

  if ! grep -Fq "/opt/VibeSensor/apps/server/.venv/bin/python" \
    "${ROOT_MNT}/etc/systemd/system/vibesensor-hotspot-self-heal.service"; then
    echo "Validation failed: hotspot self-heal service ExecStart does not reference apps/server venv"
    exit 1
  fi

  if [ ! -d "${ROOT_MNT}/etc/vibesensor" ]; then
    echo "Validation failed: missing ${ROOT_MNT}/etc/vibesensor"
    exit 1
  fi

  if [ ! -f "${ROOT_MNT}/opt/VibeSensor/apps/server/data/report_i18n.json" ]; then
    echo "Validation failed: missing ${ROOT_MNT}/opt/VibeSensor/apps/server/data/report_i18n.json"
    exit 1
  fi

  if [ ! -f "${ROOT_MNT}/opt/VibeSensor/apps/server/data/car_library.json" ]; then
    echo "Validation failed: missing ${ROOT_MNT}/opt/VibeSensor/apps/server/data/car_library.json"
    exit 1
  fi

  if [ -d "${ROOT_MNT}/opt/VibeSensor/apps/server/vibesensor" ]; then
    echo "Validation failed: source tree still present at ${ROOT_MNT}/opt/VibeSensor/apps/server/vibesensor"
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

  # Validate firmware cache baseline is present
  if [ -d "${ROOT_MNT}/var/lib/vibesensor/firmware/baseline" ]; then
    if [ ! -f "${ROOT_MNT}/var/lib/vibesensor/firmware/baseline/flash.json" ]; then
      echo "WARNING: Baseline firmware directory exists but flash.json manifest is missing"
    else
      echo "Firmware baseline bundle validated OK"
    fi
  else
    echo "WARNING: No embedded baseline firmware bundle (first-boot flash requires online updater)"
  fi

  assert_rootfs_package gpsd
  assert_rootfs_package openssh-server
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

  # Validate firmware cache CLI is available
  if ! run_qemu_chroot /opt/VibeSensor/apps/server/.venv/bin/python -c '
import vibesensor.firmware_cache
print("FIRMWARE_CACHE_MODULE_OK")
'; then
    echo "Validation failed: firmware_cache module not importable in target rootfs"
    exit 1
  fi

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
]
for mod in mods:
    importlib.import_module(mod)
print("IMPORT_VALIDATION_OK")
PY
  then
    echo "Validation failed: Python import smoke test failed in ARM chroot"
    exit 1
  fi

  if ! run_qemu_chroot /opt/VibeSensor/apps/server/.venv/bin/python - <<'PY'
import pathlib
import vibesensor

module_path = pathlib.Path(vibesensor.__file__).resolve()
if "/site-packages/" not in str(module_path):
    raise SystemExit(f"vibesensor imported from unexpected path: {module_path}")
print("WHEEL_INSTALL_PATH_OK")
PY
  then
    echo "Validation failed: vibesensor is not imported from site-packages wheel install"
    exit 1
  fi

  if run_qemu_chroot /bin/bash -lc '
ls /opt/VibeSensor/apps/server/.venv/lib/python*/site-packages/__editable__.vibesensor-*.pth >/dev/null 2>&1
'; then
    echo "Validation failed: editable install marker found; expected wheel-first runtime"
    exit 1
  fi

if ! run_qemu_chroot /bin/bash -lc '
set -e
export VIBESENSOR_DISABLE_AUTO_APP=1
export VIBESENSOR_CONTRACTS_DIR=/opt/VibeSensor/libs/shared/contracts
pkill -f "python -m vibesensor.app" >/dev/null 2>&1 || true
cp /etc/vibesensor/config.yaml /tmp/vibesensor-smoke-config.yaml
sed -i \
  -e "s#^  port: .*#  port: 18080#" \
  -e "s#^  data_listen: .*#  data_listen: 0.0.0.0:19000#" \
  -e "s#^  control_listen: .*#  control_listen: 0.0.0.0:19001#" \
  /tmp/vibesensor-smoke-config.yaml
set +e
timeout 10s /opt/VibeSensor/apps/server/.venv/bin/python -m vibesensor.app --config /tmp/vibesensor-smoke-config.yaml >/tmp/vibesensor-smoke.log 2>&1
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

  if ! run_qemu_chroot /bin/bash -lc '
set -e
rm -f /etc/ssh/ssh_host_*_key*
mkdir -p /run/sshd
chmod 0755 /run/sshd
if ! ls /etc/ssh/ssh_host_*_key >/dev/null 2>&1; then
  /usr/bin/ssh-keygen -A
fi
/usr/sbin/sshd -t
echo "SSHD_FIRST_BOOT_READINESS_OK"
'; then
    echo "Validation failed: sshd first-boot readiness test failed"
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

  if [ ! -L "${ROOT_MNT}/etc/systemd/system/multi-user.target.wants/ssh.service" ]; then
    echo "Validation failed: ssh.service is not enabled in multi-user.target"
    exit 1
  fi

  if [ -L "${ROOT_MNT}/etc/systemd/system/ssh.service" ] && \
    [ "$(readlink "${ROOT_MNT}/etc/systemd/system/ssh.service")" = "/dev/null" ]; then
    echo "Validation failed: ssh.service is masked"
    exit 1
  fi

  if [ ! -L "${ROOT_MNT}/etc/systemd/system/multi-user.target.wants/regenerate_ssh_host_keys.service" ]; then
    echo "Validation failed: regenerate_ssh_host_keys.service is not enabled"
    exit 1
  fi

  if [ ! -f "${ROOT_MNT}/etc/systemd/system/ssh.service.d/10-vibesensor-hostkeys.conf" ]; then
    echo "Validation failed: missing ssh host-key bootstrap drop-in"
    exit 1
  fi

  if ! grep -Fq 'ssh-keygen -A' "${ROOT_MNT}/etc/systemd/system/ssh.service.d/10-vibesensor-hostkeys.conf"; then
    echo "Validation failed: ssh host-key bootstrap drop-in does not generate host keys"
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

  echo "=== Validation: nmcli + rfkill + iw + dnsmasq + gpsd binaries ==="
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
else
  echo "Skipping post-build mount/chroot validation (VALIDATE=0 or FAST=1)."
fi

if [ -n "${COPY_ARTIFACT_DIR}" ]; then
  mkdir -p "${COPY_ARTIFACT_DIR}"
  cp -f "${FINAL_ARTIFACT}" "${COPY_ARTIFACT_DIR}/"
fi

cat >"${VERSION_INFO_FILE}" <<EOF
vibesensor_image_version=${BUILD_TIME_UTC}-g${BUILD_GIT_SHA}
git_sha=${BUILD_GIT_SHA}
git_branch=${BUILD_GIT_BRANCH}
source_artifact=$(basename "${FINAL_ARTIFACT}")
EOF

prune_old_artifacts \
  "${OUT_DIR}" \
  "${FINAL_ARTIFACT}" \
  "${VERSION_INFO_FILE}" \
  "${FINAL_ARTIFACT_SHA256}"

if [ -n "${COPY_ARTIFACT_DIR}" ]; then
  cp -f "${VERSION_INFO_FILE}" "${COPY_ARTIFACT_DIR}/"
fi

echo "Image artifacts available in: ${OUT_DIR}"
echo "Final artifact: ${FINAL_ARTIFACT}"
echo "Version info: ${VERSION_INFO_FILE}"
if [ -f "${INSPECT_IMG}" ]; then
  echo "Inspection image: ${INSPECT_IMG}"
fi
if [ -n "${COPY_ARTIFACT_DIR}" ]; then
  echo "Copied artifact to: ${COPY_ARTIFACT_DIR}/$(basename "${FINAL_ARTIFACT}")"
  echo "Copied version info to: ${COPY_ARTIFACT_DIR}/$(basename "${VERSION_INFO_FILE}")"
fi
