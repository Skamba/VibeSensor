rewrite_pi_gen_mirror_sources() {
  while IFS= read -r mirror_file; do
    sed -i \
      -E "s#http://raspbian\\.raspberrypi\\.com/raspbian/#${RASPBIAN_MIRROR}#g" \
      "${mirror_file}"
  done < <(rg -l "http://raspbian\\.raspberrypi\\.com/raspbian/" "${PI_GEN_DIR}")
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
    rm -f "${PI_GEN_DIR}/stage0/SKIP" "${PI_GEN_DIR}/stage1/SKIP" "${PI_GEN_DIR}/stage2/SKIP"
    echo "Full build: rebuilding all stages"
  else
    echo "Incremental build: skipping stage0/1/2 (set CLEAN=1 to rebuild from scratch)"
    touch "${PI_GEN_DIR}/stage0/SKIP"
    touch "${PI_GEN_DIR}/stage1/SKIP"
    touch "${PI_GEN_DIR}/stage2/SKIP"
  fi
}

run_pi_gen_build() {
  (
    cd "${PI_GEN_DIR}"
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
