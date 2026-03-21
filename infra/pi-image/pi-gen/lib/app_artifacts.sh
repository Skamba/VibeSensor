compute_ui_hash() {
  (
    cd "${REPO_ROOT}"
    git ls-files \
      apps/ui \
      tools/config/sync_shared_contracts_to_ui.mjs \
      | LC_ALL=C sort \
      | xargs sha256sum \
      | sha256sum \
      | awk '{print $1}'
  )
}

build_ui_bundle() {
  local ui_dir="${REPO_ROOT}/apps/ui"
  local server_static_dir="${REPO_ROOT}/apps/server/vibesensor/static"
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

  echo "Syncing UI bundle into apps/server/vibesensor/static"
  mkdir -p "${server_static_dir}"
  rsync -a --delete "${ui_dir}/dist/" "${server_static_dir}/"
}

build_app_artifacts() {
  local build_root=""
  local wheel_path=""

  echo "Preparing app artifacts..."
  build_ui_bundle

  rm -rf "${APP_ARTIFACT_DIR}"
  mkdir -p "${APP_WHEEL_DIR}" "${APP_PUBLIC_DIR}"
  rsync -a --delete "${REPO_ROOT}/apps/server/vibesensor/static/" "${APP_PUBLIC_DIR}/"

  build_root="$(mktemp -d -p "${CACHE_DIR}" app-build-XXXXXX)"
  mkdir -p "${build_root}/apps"
  rsync -a --delete \
    "${REPO_ROOT}/apps/server/" "${build_root}/apps/server/"

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
  APP_WHEEL_PATH="${APP_WHEEL_DIR}/$(basename "${wheel_path}")"
  APP_WHEEL_FILE="$(basename "${APP_WHEEL_PATH}")"

  {
    echo "build_mode=app"
    echo "generated_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "wheel=$(basename "${wheel_path}")"
    echo "wheel_sha256=$(sha256sum "${APP_WHEEL_PATH}" | awk '{print $1}')"
  } >"${APP_ARTIFACT_DIR}/manifest.txt"

  rm -rf "${build_root}"
  echo "App artifacts ready in: ${APP_ARTIFACT_DIR}"
}

require_prebuilt_app_artifacts() {
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
}
