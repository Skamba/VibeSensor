validate_build_mode() {
  if [[ "${BUILD_MODE}" != "all" && "${BUILD_MODE}" != "app" && "${BUILD_MODE}" != "image" ]]; then
    echo "Invalid BUILD_MODE='${BUILD_MODE}'. Use one of: all, app, image."
    exit 1
  fi
}

ensure_output_dirs() {
  mkdir -p "${CACHE_DIR}" "${OUT_DIR}" "${APP_WHEEL_DIR}"
}

apply_fast_mode() {
  if [ "${FAST}" = "1" ]; then
    VALIDATE=0
  fi
}

validate_first_user_credentials() {
  if [ -z "${VS_FIRST_USER_NAME}" ] || [ -z "${VS_FIRST_USER_PASS}" ]; then
    echo "VS_FIRST_USER_NAME and VS_FIRST_USER_PASS must be non-empty to avoid first-boot user prompt."
    exit 1
  fi
}

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
  require_cmd qemu-arm
  require_cmd qemu-arm-static
}

require_validation_prereqs() {
  require_cmd sudo
  require_cmd losetup
  require_cmd mount
  require_cmd umount
  require_cmd awk
  require_cmd qemu-arm-static
  require_cmd python3
}

ensure_docker_available() {
  if ! docker info >/dev/null 2>&1; then
    echo "Docker daemon is not available for current user."
    echo "Start Docker and/or add your user to the docker group."
    exit 1
  fi
}
