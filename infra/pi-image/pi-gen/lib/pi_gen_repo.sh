rewrite_pi_gen_mirror_sources() {
  while IFS= read -r -d '' mirror_file; do
    sed -i \
      -E "s#http://raspbian\\.raspberrypi\\.com/raspbian/#${RASPBIAN_MIRROR}#g" \
      "${mirror_file}"
  done < <(grep -rlZ "http://raspbian\\.raspberrypi\\.com/raspbian/" "${PI_GEN_DIR}" || true)
}

patch_export_image_boot_size() {
  local export_prerun="${PI_GEN_DIR}/export-image/prerun.sh"
  local stock_boot_size='BOOT_SIZE="$((512 * 1024 * 1024))"'
  local patched_boot_size='BOOT_SIZE="$((1024 * 1024 * 1024))"'

  if ! grep -Fq "${stock_boot_size}" "${export_prerun}"; then
    if grep -Fq "${patched_boot_size}" "${export_prerun}"; then
      return
    fi
    echo "Unexpected export-image/prerun.sh boot-size layout in ${export_prerun}"
    exit 1
  fi

  # Current Raspberry Pi kernel packages overflow the stock 512 MiB boot
  # partition during export-image upgrades, so keep the generated image bootfs
  # at 1 GiB until upstream sizing catches up.
  sed -i \
    's/BOOT_SIZE="\$((512 \* 1024 \* 1024))"/BOOT_SIZE="$((1024 * 1024 * 1024))"/' \
    "${export_prerun}"
}

patch_build_docker_qemu_interpreter() {
  local build_docker="${PI_GEN_DIR}/build-docker.sh"
  local stock_check='if ! qemu_arm=$(which qemu-arm) ; then'
  local patched_check='if ! qemu_arm=$(command -v qemu-arm-static 2>/dev/null) && ! qemu_arm=$(command -v qemu-arm 2>/dev/null) ; then'

  if grep -Fq "${patched_check}" "${build_docker}"; then
    return
  fi
  if ! grep -Fq "${stock_check}" "${build_docker}"; then
    echo "Unexpected build-docker.sh qemu lookup in ${build_docker}"
    exit 1
  fi

  sed -i \
    's/if ! qemu_arm=$(which qemu-arm) ; then/if ! qemu_arm=$(command -v qemu-arm-static 2>\/dev\/null) \&\& ! qemu_arm=$(command -v qemu-arm 2>\/dev\/null) ; then/' \
    "${build_docker}"
}

patch_build_docker_base_image() {
  local build_docker="${PI_GEN_DIR}/build-docker.sh"
  local stock_block='case "$(uname -m)" in
  x86_64|aarch64)
    BASE_IMAGE=i386/debian:trixie
    ;;
  *)
    BASE_IMAGE=debian:trixie
    ;;
esac'
  local patched_block='case "$(uname -m)" in
  x86_64)
    BASE_IMAGE=i386/debian:trixie
    ;;
  *)
    BASE_IMAGE=debian:trixie
    ;;
esac'

  BUILD_DOCKER="${build_docker}" STOCK_BLOCK="${stock_block}" PATCHED_BLOCK="${patched_block}" "${VS_PYTHON_BIN}" - <<'PY'
from pathlib import Path
import os
import sys

path = Path(os.environ["BUILD_DOCKER"])
stock = os.environ["STOCK_BLOCK"]
patched = os.environ["PATCHED_BLOCK"]
text = path.read_text(encoding="utf-8")

if patched in text:
    raise SystemExit(0)
if stock not in text:
    raise SystemExit(
        f"Unexpected build-docker.sh base-image selection in {path}"
    )

path.write_text(text.replace(stock, patched), encoding="utf-8")
PY
}

refresh_stage0_bootstrap_keyring() {
  local vendored_keyring="${TEMPLATE_ROOT}/stage0-bootstrap-raspberrypi.gpg"
  local upstream_keyring="${PI_GEN_DIR}/stage0/files/raspberrypi.gpg"

  if cmp -s "${vendored_keyring}" "${upstream_keyring}"; then
    return
  fi

  # Upstream pi-gen still ships an armhf bootstrap keyring whose Raspbian key
  # only has SHA-1 self-signatures, which makes trixie debootstrap reject the
  # InRelease signature on modern GnuPG policies.
  cp "${vendored_keyring}" "${upstream_keyring}"
}

set_base_stage_skip_files() {
  local state="$1"
  local stage=""

  for stage in 0 1 2; do
    case "${state}" in
      present)
        touch "${PI_GEN_DIR}/stage${stage}/SKIP"
        ;;
      absent)
        rm -f "${PI_GEN_DIR}/stage${stage}/SKIP"
        ;;
      *)
        echo "Unsupported SKIP marker state: ${state}"
        exit 1
        ;;
    esac
  done
}

prepare_pi_gen_repo() {
  if [ ! -d "${PI_GEN_DIR}/.git" ]; then
    git clone --depth 1 --branch "${PI_GEN_REF}" https://github.com/RPi-Distro/pi-gen.git "${PI_GEN_DIR}"
  else
    git -C "${PI_GEN_DIR}" fetch --depth 1 origin "${PI_GEN_REF}"
    git -C "${PI_GEN_DIR}" checkout -B "${PI_GEN_REF}" FETCH_HEAD
    git -C "${PI_GEN_DIR}" reset --hard FETCH_HEAD
  fi

  rewrite_pi_gen_mirror_sources
  patch_export_image_boot_size
  patch_build_docker_base_image
  patch_build_docker_qemu_interpreter
  refresh_stage0_bootstrap_keyring
}

configure_incremental_build() {
  local prev_work_exists=0
  if docker ps -a --format '{{.Names}}' | grep -Fxq pigen_work; then
    prev_work_exists=1
  fi

  if [ "${CLEAN}" = "1" ] || [ "${prev_work_exists}" = "0" ]; then
    if [ "${prev_work_exists}" = "1" ]; then
      echo "CLEAN=1: removing previous pigen_work container"
      docker rm -v pigen_work >/dev/null
    fi
    set_base_stage_skip_files absent
    echo "Full build: rebuilding all stages"
  else
    echo "Incremental build: skipping stage0/1/2 (set CLEAN=1 to rebuild from scratch)"
    set_base_stage_skip_files present
  fi
}

run_pi_gen_build() {
  (
    cd "${PI_GEN_DIR}" || exit
    CONTINUE=1 PRESERVE_CONTAINER=1 ./build-docker.sh
  )
}

copy_exported_image_artifacts() {
  find "${PI_GEN_DIR}/deploy" -maxdepth 1 -type f \
    \( -name "*${IMG_SUFFIX}*.img" -o -name "*${IMG_SUFFIX}*.img.xz" -o -name "*${IMG_SUFFIX}*.zip" -o -name "*${IMG_SUFFIX}*.sha256" \) \
    -exec cp -f {} "${OUT_DIR}/" \;

  if ! find "${OUT_DIR}" -maxdepth 1 -type f \( -name "*${IMG_SUFFIX}*.img" -o -name "*${IMG_SUFFIX}*.img.xz" -o -name "*${IMG_SUFFIX}*.zip" \) | grep -q .; then
    echo "No exported image artifacts matching IMG_SUFFIX='${IMG_SUFFIX}' were copied to ${OUT_DIR}"
    exit 1
  fi
}
