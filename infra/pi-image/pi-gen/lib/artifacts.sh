choose_final_artifact() {
  local base_dir="$1"
  local candidate=""

  candidate="$(find "${base_dir}" -maxdepth 1 -type f -name "image_*${IMG_SUFFIX}*.img" | sort -r | head -n 1 || true)"
  if [ -n "${candidate}" ]; then
    printf '%s\n' "${candidate}"
    return 0
  fi

  candidate="$(find "${base_dir}" -maxdepth 1 -type f -name "image_*${IMG_SUFFIX}*.img.xz" | sort -r | head -n 1 || true)"
  if [ -n "${candidate}" ]; then
    printf '%s\n' "${candidate}"
    return 0
  fi

  candidate="$(find "${base_dir}" -maxdepth 1 -type f -name "image_*${IMG_SUFFIX}*.zip" | sort -r | head -n 1 || true)"
  if [ -n "${candidate}" ]; then
    printf '%s\n' "${candidate}"
    return 0
  fi

  candidate="$(find "${base_dir}" -maxdepth 1 -type f -name "*${IMG_SUFFIX}*.zip" ! -name "latest${IMG_SUFFIX}.*" | sort -r | head -n 1 || true)"
  if [ -n "${candidate}" ]; then
    printf '%s\n' "${candidate}"
    return 0
  fi

  return 1
}

prune_old_artifacts() {
  local base_dir="$1"
  local keep_file="$2"
  local keep_version_info="$3"
  local keep_sha256="$4"
  local path=""

  while IFS= read -r path; do
    case "${path}" in
      "${keep_file}"|"${keep_version_info}"|"${keep_sha256}")
        continue
        ;;
    esac
    rm -f "${path}"
  done < <(
    find "${base_dir}" -maxdepth 1 -type f \
      \( -name "*${IMG_SUFFIX}*.img" -o -name "*${IMG_SUFFIX}*.img.xz" -o -name "*${IMG_SUFFIX}*.zip" -o -name "*${IMG_SUFFIX}*.sha256" -o -name "*${IMG_SUFFIX}*.version.txt" \) \
      | sort
  )
}

write_version_info() {
  local version_info_file="$1"
  local final_artifact="$2"
  local build_time_utc="$3"
  local build_git_sha="$4"
  local build_git_branch="$5"

  cat >"${version_info_file}" <<EOF_INNER
vibesensor_image_version=${build_time_utc}-g${build_git_sha}
git_sha=${build_git_sha}
git_branch=${build_git_branch}
source_artifact=$(basename "${final_artifact}")
EOF_INNER
}
