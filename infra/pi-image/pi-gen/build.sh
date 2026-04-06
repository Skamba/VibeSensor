#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/prereqs.sh"
source "${SCRIPT_DIR}/lib/mirror.sh"
source "${SCRIPT_DIR}/lib/app_artifacts.sh"
source "${SCRIPT_DIR}/lib/pi_gen_repo.sh"
source "${SCRIPT_DIR}/lib/stage_assembly.sh"
source "${SCRIPT_DIR}/lib/artifacts.sh"

builds_app_artifacts() {
  [[ "${BUILD_MODE}" == "app" || "${BUILD_MODE}" == "all" ]]
}

builds_image_artifacts() {
  [[ "${BUILD_MODE}" == "image" || "${BUILD_MODE}" == "all" ]]
}

init_pi_gen_env
validate_build_mode
ensure_output_dirs
apply_fast_mode
validate_first_user_credentials

if builds_app_artifacts; then
  require_app_prereqs
fi

if builds_image_artifacts; then
  require_image_prereqs
  ensure_docker_available
  RASPBIAN_MIRROR="$(select_raspbian_mirror)"
  echo "Using Raspbian mirror: ${RASPBIAN_MIRROR}"
fi

if builds_app_artifacts; then
  build_app_artifacts
fi

if [[ "${BUILD_MODE}" == "app" ]]; then
  echo "Build mode 'app' complete."
  exit 0
fi

require_prebuilt_app_artifacts
prepare_pi_gen_repo
prepare_pi_gen_stage
configure_incremental_build
run_pi_gen_build
copy_exported_image_artifacts

FINAL_ARTIFACT="$(choose_final_artifact "${OUT_DIR}" || true)"
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

if [ "${VALIDATE}" = "1" ]; then
  "${SCRIPT_DIR}/validate-image.sh" "${FINAL_ARTIFACT}"
else
  echo "Skipping post-build mount/chroot validation (VALIDATE=0 or FAST=1)."
fi

if [ -n "${COPY_ARTIFACT_DIR}" ]; then
  mkdir -p "${COPY_ARTIFACT_DIR}"
  cp -f "${FINAL_ARTIFACT}" "${COPY_ARTIFACT_DIR}/"
fi

write_version_info \
  "${VERSION_INFO_FILE}" \
  "${FINAL_ARTIFACT}" \
  "${BUILD_TIME_UTC}" \
  "${BUILD_GIT_SHA}" \
  "${BUILD_GIT_BRANCH}" \
  "${VALIDATED_IMAGE_PYTHON_VERSION:-}" \
  "${VALIDATED_IMAGE_PYTHON_FLOOR:-}"

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
if [ -n "${COPY_ARTIFACT_DIR}" ]; then
  echo "Copied artifact to: ${COPY_ARTIFACT_DIR}/$(basename "${FINAL_ARTIFACT}")"
  echo "Copied version info to: ${COPY_ARTIFACT_DIR}/$(basename "${VERSION_INFO_FILE}")"
fi
