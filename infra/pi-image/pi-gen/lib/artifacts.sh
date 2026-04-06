latest_artifact_matching() {
  local base_dir="$1"
  shift
  local candidate=""
  local pattern=""

  for pattern in "$@"; do
    candidate="$(find "${base_dir}" -maxdepth 1 -type f -name "${pattern}" | sort -r | head -n 1 || true)"
    if [ -n "${candidate}" ]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  return 1
}

choose_final_artifact() {
  local base_dir="$1"
  latest_artifact_matching \
    "${base_dir}" \
    "image_*${IMG_SUFFIX}*.img" \
    "image_*${IMG_SUFFIX}*.img.xz" \
    "image_*${IMG_SUFFIX}*.zip"
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
  local image_runtime_python_version="${6:-}"
  local image_runtime_python_floor="${7:-}"

  {
    echo "vibesensor_image_version=${build_time_utc}-g${build_git_sha}"
    echo "git_sha=${build_git_sha}"
    echo "git_branch=${build_git_branch}"
    echo "source_artifact=$(basename "${final_artifact}")"
    if [ -n "${image_runtime_python_version}" ]; then
      echo "image_runtime_python_version=${image_runtime_python_version}"
    fi
    if [ -n "${image_runtime_python_floor}" ]; then
      echo "image_runtime_python_floor=${image_runtime_python_floor}"
    fi
  } >"${version_info_file}"
}
