sync_stage_repo_snapshot() {
  rm -rf "${STAGE_DIR}"
  mkdir -p "${STAGE_REPO_DIR}"

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
    --exclude "apps/server/tests/" \
    --exclude "apps/server/tests_e2e/" \
    --exclude "docs/" \
    --exclude "examples/" \
    --exclude "firmware/" \
    --exclude "hardware/" \
    --exclude "tools/tests/" \
    --exclude "apps/server/data/" \
    --exclude "infra/pi-image/pi-gen/.cache/" \
    --exclude "infra/pi-image/pi-gen/.pip-cache-stage/" \
    --exclude "infra/pi-image/pi-gen/out/" \
    "${REPO_ROOT}/" "${STAGE_REPO_DIR}/"
}

stage_app_artifacts() {
  mkdir -p "${STAGE_REPO_DIR}/apps/server/vibesensor/static"
  rsync -a --delete "${APP_PUBLIC_DIR}/" "${STAGE_REPO_DIR}/apps/server/vibesensor/static/"

  mkdir -p "${STAGE_STEP_DIR}/files/opt/vibesensor-artifacts/wheels"
  cp -f "${APP_WHEEL_PATH}" "${STAGE_STEP_DIR}/files/opt/vibesensor-artifacts/wheels/${APP_WHEEL_FILE}"
}

render_stage_templates() {
  local export_trim_dir="${PI_GEN_DIR}/export-image/04-vibesensor-trim"

  render_template_file \
    "${TEMPLATE_ROOT}/stage-vibesensor/prerun.sh.template" \
    "${STAGE_DIR}/prerun.sh" \
    "__RASPBIAN_MIRROR__" "${RASPBIAN_MIRROR}"
  chmod +x "${STAGE_DIR}/prerun.sh"

  render_template_file \
    "${TEMPLATE_ROOT}/stage-vibesensor/00-vibesensor/00-run.sh.template" \
    "${STAGE_STEP_DIR}/00-run.sh" \
    "__APP_WHEEL_FILE__" "${APP_WHEEL_FILE}" \
    "__SSH_FIRST_BOOT_DEBUG__" "${SSH_FIRST_BOOT_DEBUG}"
  chmod +x "${STAGE_STEP_DIR}/00-run.sh"

  install -m 0644 \
    "${TEMPLATE_ROOT}/stage-vibesensor/00-vibesensor/00-packages" \
    "${STAGE_STEP_DIR}/00-packages"

  touch "${STAGE_DIR}/EXPORT_IMAGE"
  touch "${PI_GEN_DIR}/stage2/SKIP_IMAGES"

  mkdir -p "${export_trim_dir}"
  install -m 0755 \
    "${TEMPLATE_ROOT}/export-image/04-vibesensor-trim/00-run.sh" \
    "${export_trim_dir}/00-run.sh"

  render_template_file \
    "${TEMPLATE_ROOT}/pi-gen-config.template" \
    "${PI_GEN_DIR}/config" \
    "__IMG_SUFFIX__" "${IMG_SUFFIX}" \
    "__PI_IMAGE_RELEASE__" "${PI_IMAGE_RELEASE}" \
    "__VS_FIRST_USER_NAME__" "${VS_FIRST_USER_NAME}" \
    "__VS_FIRST_USER_PASS__" "${VS_FIRST_USER_PASS}" \
    "__VS_WPA_COUNTRY__" "${VS_WPA_COUNTRY}"
}

prepare_pi_gen_stage() {
  sync_stage_repo_snapshot
  stage_app_artifacts
  render_stage_templates
}
