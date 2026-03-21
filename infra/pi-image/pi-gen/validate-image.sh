#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/prereqs.sh"
source "${SCRIPT_DIR}/lib/artifacts.sh"
source "${SCRIPT_DIR}/lib/image_validation.sh"

init_pi_gen_env
ensure_output_dirs
require_validation_prereqs

ARTIFACT_PATH="${1:-}"
if [ -z "${ARTIFACT_PATH}" ]; then
  ARTIFACT_PATH="$(choose_final_artifact "${OUT_DIR}" || true)"
  if [ -z "${ARTIFACT_PATH}" ]; then
    echo "Failed to select a final artifact in ${OUT_DIR}"
    exit 1
  fi
fi

validate_image_artifact "${ARTIFACT_PATH}"
echo "Validation complete for: ${ARTIFACT_PATH}"
