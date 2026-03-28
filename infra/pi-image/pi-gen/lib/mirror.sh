normalize_mirror() {
  local value="$1"
  value="${value%/}/"
  printf '%s\n' "${value}"
}

mirror_release_url() {
  local base="$1"
  printf '%sdists/%s/Release\n' "$(normalize_mirror "${base}")" "${PI_IMAGE_RELEASE}"
}

probe_mirror() {
  local base="$1"
  local release_url
  release_url="$(mirror_release_url "${base}")"
  curl -fsI --max-time 10 "${release_url}" >/dev/null 2>&1
}

select_raspbian_mirror() {
  local candidate=""
  if [ -n "${RASPBIAN_MIRROR}" ]; then
    candidate="$(normalize_mirror "${RASPBIAN_MIRROR}")"
    if ! probe_mirror "${candidate}"; then
      echo "Configured RASPBIAN_MIRROR is unreachable: ${candidate}"
      exit 1
    fi
    printf '%s\n' "${candidate}"
    return 0
  fi

  for candidate in "${RASPBIAN_MIRROR_FALLBACKS[@]}"; do
    if probe_mirror "${candidate}"; then
      printf '%s\n' "$(normalize_mirror "${candidate}")"
      return 0
    fi
  done
  echo "No reachable Raspbian mirror found."
  exit 1
}
