# shellcheck disable=SC2034  # This library initializes globals consumed by other pi-gen libraries.
init_pi_gen_env() {
  SCRIPT_DIR="${SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
  REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../.." && pwd)}"
  TEMPLATE_ROOT="${SCRIPT_DIR}/templates"
  CACHE_DIR="${SCRIPT_DIR}/.cache"
  PI_GEN_DIR="${CACHE_DIR}/pi-gen"
  PI_GEN_REF="${PI_GEN_REF:-master}"
  PI_IMAGE_RELEASE="${PI_IMAGE_RELEASE:-trixie}"
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
  VS_PYTHON_BIN="${VS_PYTHON_BIN:-python3}"
  SSH_FIRST_BOOT_DEBUG="${SSH_FIRST_BOOT_DEBUG:-0}"
  VALIDATE="${VALIDATE:-1}"
  FAST="${FAST:-0}"
  FORCE_UI_BUILD="${FORCE_UI_BUILD:-0}"
  COPY_ARTIFACT_DIR="${COPY_ARTIFACT_DIR:-}"
  UI_HASH_FILE="${CACHE_DIR}/ui-build.hash"
  CLEAN="${CLEAN:-0}"
  RASPBIAN_MIRROR="${RASPBIAN_MIRROR:-}"
  RASPBIAN_MIRROR_FALLBACKS=(
    "http://raspbian.raspberrypi.com/raspbian/"
    "http://mirror.init7.net/raspbian/raspbian/"
    "http://mirrors.ustc.edu.cn/raspbian/raspbian/"
    "http://ftp.halifax.rwth-aachen.de/raspbian/raspbian/"
    "http://mirror.ox.ac.uk/sites/archive.raspbian.org/archive/raspbian/"
    # The HTTPS archive endpoint is a useful fallback, but recent GitHub-hosted
    # runner builds have intermittently hit TLS EOFs while fetching large
    # package sets from it. Prefer the standard HTTP mirrors first and keep the
    # archive endpoint as the last resort.
    "https://archive.raspbian.org/raspbian/"
  )

  if [ "${USE_QEMU:-0}" = "1" ]; then
    IMG_SUFFIX="${IMG_SUFFIX_BASE}-qemu"
  else
    IMG_SUFFIX="${IMG_SUFFIX_BASE}"
  fi
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    exit 1
  fi
}

escape_sed_replacement() {
  printf '%s' "$1" | sed -e 's/[\\/&]/\\&/g' -e 's/#/\\#/g'
}

render_template_file() {
  local template="$1"
  local output="$2"
  shift 2

  mkdir -p "$(dirname "${output}")"
  cp "${template}" "${output}"

  while [ "$#" -gt 0 ]; do
    local placeholder="$1"
    local value="$2"
    shift 2
    sed -i "s#${placeholder}#$(escape_sed_replacement "${value}")#g" "${output}"
  done
}
