#!/usr/bin/env bash
set -euo pipefail

LOG_DIR=${1:-/var/log/wifi}
OUT_ZIP=${2:-/var/log/wifi-export.zip}

if ! command -v zip >/dev/null 2>&1; then
  echo "zip command not found"
  exit 1
fi

if [ ! -d "${LOG_DIR}" ]; then
  echo "log directory does not exist: ${LOG_DIR}"
  exit 1
fi

tmp_dir=$(mktemp -d)
trap 'rm -rf "${tmp_dir}"' EXIT

cp -a "${LOG_DIR}"/. "${tmp_dir}"/ 2>/dev/null || true
(
  cd "${tmp_dir}"
  zip -q -r "${OUT_ZIP}" .
)

echo "Wi-Fi logs exported to ${OUT_ZIP}"
