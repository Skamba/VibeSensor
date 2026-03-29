#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
BUILD_ROOT="${SCRIPT_DIR}/.build"
WORK_ROOT="${BUILD_ROOT}/work"
SOURCE_TREE_DIR="${WORK_ROOT}/source-tree"
WHEELHOUSE_DIR="${WORK_ROOT}/wheelhouse"
FIRMWARE_CACHE_DIR="${WORK_ROOT}/firmware-cache"
OUT_DIR="${SCRIPT_DIR}/out"
HOST_VENV_DIR="${BUILD_ROOT}/host-tools-venv"
KAS_BUILD_DIR="${BUILD_ROOT}/kas-build"
KAS_WORK_DIR="${BUILD_ROOT}/kas-work"
GENERATED_KAS_FILE="${BUILD_ROOT}/generated-artifacts.yml"
VALIDATE="${VALIDATE:-1}"
KAS_EXTRA_CONFIG="${KAS_EXTRA_CONFIG:-${SCRIPT_DIR}/kas/vibesensor-ci.yml}"
BUILD_LABEL="${BUILD_LABEL:-$(date -u +%Y%m%dT%H%M%SZ)}"
VS_FIRST_USER_NAME="${VS_FIRST_USER_NAME:-pi}"
VS_FIRST_USER_PASS="${VS_FIRST_USER_PASS:-vibesensor}"
export LANG="${LANG:-en_US.UTF-8}"
export LC_ALL="${LC_ALL:-en_US.UTF-8}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

assert_python_compatible() {
  if ! python3 - <<'PY' >/dev/null
import sys
raise SystemExit(0 if sys.version_info >= (3, 13) else 1)
PY
  then
    echo "python3 must be version 3.13 or newer for the VibeSensor wheel build" >&2
    exit 1
  fi
}

assert_supported_host() {
  if [ "$(uname -m)" != "aarch64" ] && [ "${ALLOW_UNSUPPORTED_HOST:-0}" != "1" ]; then
    echo "Yocto image preparation currently requires an ARM64 Linux host because the wheelhouse and rootfs post-processing are native-arm oriented." >&2
    echo "Set ALLOW_UNSUPPORTED_HOST=1 only for limited config checks; full image builds are intended for ubuntu-24.04-arm." >&2
    exit 1
  fi
}

build_ui_bundle() {
  local ui_dir="${REPO_ROOT}/apps/ui"
  if [ ! -d "${ui_dir}/node_modules" ]; then
    (cd "${ui_dir}" && npm ci)
  fi
  (cd "${ui_dir}" && npm run build)
}

prepare_source_tree() {
  rm -rf "${SOURCE_TREE_DIR}"
  mkdir -p "${SOURCE_TREE_DIR}"
  rsync -a --delete \
    --exclude '.git/' \
    --exclude '.github/' \
    --exclude '.githooks/' \
    --exclude '.ai-temp/' \
    --exclude '.venv/' \
    --exclude '.pytest_cache/' \
    --exclude '.ruff_cache/' \
    --exclude '.mypy_cache/' \
    --exclude '.cache/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude 'artifacts/' \
    --exclude 'build/' \
    --exclude 'poky/' \
    --exclude 'meta-openembedded/' \
    --exclude 'meta-raspberrypi/' \
    --exclude '$MNT/' \
    --exclude 'apps/ui/' \
    --exclude 'apps/server/tests/' \
    --exclude 'apps/server/tests_e2e/' \
    --exclude 'docs/' \
    --exclude 'examples/' \
    --exclude 'firmware/' \
    --exclude 'hardware/' \
    --exclude 'tools/tests/' \
    --exclude 'infra/pi-image/pi-gen/.cache/' \
    --exclude 'infra/pi-image/pi-gen/out/' \
    --exclude 'infra/pi-image/yocto/.build/' \
    "${REPO_ROOT}/" "${SOURCE_TREE_DIR}/"
  mkdir -p "${SOURCE_TREE_DIR}/apps/server/vibesensor/static"
  rsync -a --delete "${REPO_ROOT}/apps/ui/dist/" "${SOURCE_TREE_DIR}/apps/server/vibesensor/static/"
}

ensure_host_venv() {
  if [ ! -x "${HOST_VENV_DIR}/bin/python" ]; then
    python3 -m venv "${HOST_VENV_DIR}"
  fi
  "${HOST_VENV_DIR}/bin/python" -m pip install --upgrade pip build wheel >/dev/null
}

build_wheelhouse() {
  rm -rf "${WHEELHOUSE_DIR}"
  mkdir -p "${WHEELHOUSE_DIR}"
  (
    cd "${SOURCE_TREE_DIR}"
    "${HOST_VENV_DIR}/bin/python" -m build --wheel apps/server >/dev/null
  )

  local app_wheel
  app_wheel="$(find "${SOURCE_TREE_DIR}/apps/server/dist" -maxdepth 1 -type f -name 'vibesensor-*.whl' | sort | tail -n 1)"
  if [ -z "${app_wheel}" ]; then
    echo "Failed to build vibesensor wheel" >&2
    exit 1
  fi
  cp -f "${app_wheel}" "${WHEELHOUSE_DIR}/"
  APP_WHEEL_BASENAME="$(basename "${app_wheel}")"
  export APP_WHEEL_BASENAME

  mapfile -t runtime_reqs < <(
    SOURCE_TREE_DIR="${SOURCE_TREE_DIR}" python3 - <<'PY'
from pathlib import Path
import os
import tomllib

pyproject = Path(os.environ["SOURCE_TREE_DIR"]) / "apps" / "server" / "pyproject.toml"
data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
project = data["project"]
for dep in project.get("dependencies", []):
    print(dep)
for dep in project.get("optional-dependencies", {}).get("esp", []):
    print(dep)
print("pip>=24,<26")
print("setuptools>=68,<83")
print("wheel>=0.45,<1")
PY
  )
  "${HOST_VENV_DIR}/bin/python" -m pip download --dest "${WHEELHOUSE_DIR}" --only-binary=:all: --prefer-binary "${runtime_reqs[@]}"
}

prepare_firmware_cache() {
  rm -rf "${FIRMWARE_CACHE_DIR}"
  mkdir -p "${FIRMWARE_CACHE_DIR}"
  local runtime_venv="${BUILD_ROOT}/host-runtime-venv"
  rm -rf "${runtime_venv}"
  python3 -m venv "${runtime_venv}"
  if ! "${runtime_venv}/bin/python" -m pip install --no-index --find-links "${WHEELHOUSE_DIR}" "${WHEELHOUSE_DIR}/${APP_WHEEL_BASENAME}[esp]" >/dev/null; then
    rm -rf "${runtime_venv}"
    return 0
  fi
  if "${runtime_venv}/bin/vibesensor-fw-refresh" --cache-dir "${FIRMWARE_CACHE_DIR}" >/dev/null 2>&1; then
    if [ -d "${FIRMWARE_CACHE_DIR}/current" ] && [ -f "${FIRMWARE_CACHE_DIR}/current/flash.json" ]; then
      cp -a "${FIRMWARE_CACHE_DIR}/current" "${FIRMWARE_CACHE_DIR}/baseline"
      FIRMWARE_CACHE_DIR="${FIRMWARE_CACHE_DIR}" "${runtime_venv}/bin/python" - <<'PY'
import json
import os
from pathlib import Path

meta_path = Path(os.environ["FIRMWARE_CACHE_DIR"]) / "baseline" / "_meta.json"
if meta_path.exists():
    payload = json.loads(meta_path.read_text())
    payload["source"] = "baseline"
    meta_path.write_text(json.dumps(payload, indent=2) + "\n")
PY
    fi
  else
    echo "WARNING: Firmware baseline prefetch failed; image will rely on the online updater for first refresh." >&2
  fi
  rm -rf "${runtime_venv}"
}

write_artifact_manifest() {
  local manifest_path="${WORK_ROOT}/app-artifacts-manifest.json"
  REPO_ROOT="${REPO_ROOT}" \
  WHEELHOUSE_DIR="${WHEELHOUSE_DIR}" \
  FIRMWARE_CACHE_DIR="${FIRMWARE_CACHE_DIR}" \
  BUILD_LABEL="${BUILD_LABEL}" \
  python3 - <<'PY' > "${manifest_path}"
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


repo_root = Path(os.environ["REPO_ROOT"])
wheelhouse = Path(os.environ["WHEELHOUSE_DIR"])
firmware_cache = Path(os.environ["FIRMWARE_CACHE_DIR"])
payload = {
    "build_label": os.environ["BUILD_LABEL"],
    "git_sha": subprocess.check_output(["git", "-C", str(repo_root), "rev-parse", "HEAD"], text=True).strip(),
    "git_branch": subprocess.check_output(["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip(),
    "wheelhouse": [
        {"name": path.name, "sha256": sha256(path)}
        for path in sorted(wheelhouse.glob("*"))
        if path.is_file()
    ],
    "firmware_baseline_present": (firmware_cache / "baseline" / "flash.json").is_file(),
}
print(json.dumps(payload, indent=2))
PY
  ARTIFACTS_MANIFEST="${manifest_path}"
  export ARTIFACTS_MANIFEST
}

generate_kas_overlay() {
  local pass_hash
  pass_hash="$(openssl passwd -6 -salt vibesensor "${VS_FIRST_USER_PASS}")"
  cat > "${GENERATED_KAS_FILE}" <<EOF
header:
  version: 14
local_conf_header:
  vibesensor-artifacts: |
    VIBESENSOR_SOURCE_TREE = "${SOURCE_TREE_DIR}"
    VIBESENSOR_WHEELHOUSE_DIR = "${WHEELHOUSE_DIR}"
    VIBESENSOR_FIRMWARE_CACHE_DIR = "${FIRMWARE_CACHE_DIR}"
    VIBESENSOR_ARTIFACTS_MANIFEST = "${ARTIFACTS_MANIFEST}"
    VIBESENSOR_BUILD_LABEL = "${BUILD_LABEL}"
    VIBESENSOR_FIRST_USER_NAME = "${VS_FIRST_USER_NAME}"
    VIBESENSOR_FIRST_USER_PASS_HASH = "${pass_hash}"
EOF
}

run_kas_build() {
  rm -rf "${KAS_BUILD_DIR}"
  mkdir -p "${KAS_BUILD_DIR}" "${KAS_WORK_DIR}"
  export KAS_BUILD_DIR
  export KAS_WORK_DIR
  local kas_stack="${SCRIPT_DIR}/kas/vibesensor-base.yml:${GENERATED_KAS_FILE}"
  if [ -n "${KAS_EXTRA_CONFIG}" ] && [ -f "${KAS_EXTRA_CONFIG}" ]; then
    kas_stack="${kas_stack}:${KAS_EXTRA_CONFIG}"
  fi
  kas build "${kas_stack}"
}

collect_outputs() {
  local deploy_dir="${KAS_BUILD_DIR}/tmp/deploy/images/raspberrypi-armv8"
  local source_artifact
  source_artifact="$(find "${deploy_dir}" -maxdepth 1 -type f -name 'vibesensor-image-raspberrypi-armv8.rootfs.wic.bz2' | sort | tail -n 1 || true)"
  if [ -z "${source_artifact}" ]; then
    echo "No Yocto image artifact found in ${deploy_dir}" >&2
    exit 1
  fi

  local basename="image_${BUILD_LABEL}-vibesensor-rpi-universal.wic.bz2"
  cp -f "${source_artifact}" "${OUT_DIR}/${basename}"
  sha256sum "${OUT_DIR}/${basename}" > "${OUT_DIR}/${basename}.sha256"

  DEPLOY_DIR="${deploy_dir}" \
  SOURCE_ARTIFACT="${source_artifact}" \
  OUT_DIR="${OUT_DIR}" \
  BASENAME="${basename}" \
  BUILD_LABEL="${BUILD_LABEL}" \
  REPO_ROOT="${REPO_ROOT}" \
  python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

out_dir = Path(os.environ["OUT_DIR"])
source_artifact = Path(os.environ["SOURCE_ARTIFACT"])
deploy_dir = Path(os.environ["DEPLOY_DIR"])
payload = {
    "build_label": os.environ["BUILD_LABEL"],
    "machine": "raspberrypi-armv8",
    "source_artifact": source_artifact.name,
    "published_artifact": os.environ["BASENAME"],
    "git_sha": subprocess.check_output(["git", "-C", os.environ["REPO_ROOT"], "rev-parse", "HEAD"], text=True).strip(),
    "git_branch": subprocess.check_output(["git", "-C", os.environ["REPO_ROOT"], "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip(),
    "deploy_files": sorted(path.name for path in deploy_dir.iterdir() if path.is_file()),
}
(out_dir / f"{os.environ['BASENAME']}.manifest.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
}

main() {
  require_cmd git
  require_cmd rsync
  require_cmd npm
  require_cmd python3
  require_cmd kas
  require_cmd openssl
  require_cmd sha256sum
  require_cmd unzip
  require_cmd losetup
  require_cmd mount
  require_cmd umount

  assert_python_compatible
  assert_supported_host
  mkdir -p "${BUILD_ROOT}" "${WORK_ROOT}" "${OUT_DIR}"
  build_ui_bundle
  prepare_source_tree
  ensure_host_venv
  build_wheelhouse
  prepare_firmware_cache || true
  write_artifact_manifest
  generate_kas_overlay
  run_kas_build
  collect_outputs
  if [ "${VALIDATE}" = "1" ]; then
    VS_FIRST_USER_NAME="${VS_FIRST_USER_NAME}" VS_FIRST_USER_PASS="${VS_FIRST_USER_PASS}" \
      "${SCRIPT_DIR}/validate-image.sh" "$(find "${OUT_DIR}" -maxdepth 1 -type f -name 'image_*vibesensor-rpi-universal.wic.bz2' | sort | tail -n 1)"
  fi
  echo "Yocto image artifacts available in: ${OUT_DIR}"
}

main "$@"
