#!/usr/bin/env bash
# Allowlist wrapper for the root commands the VibeSensor updater needs.
# vibesensor_privileged_helper.py runs it as root for "update" requests that
# the server sends over vibesensor-privileged.socket; it is the security
# boundary for those requests, so it only runs the exact commands below.
set -euo pipefail

ALLOWED_COMMAND_NAMES=("nmcli" "python3" "systemd-run" "systemctl")

if [ $# -lt 1 ]; then
  echo "Usage: $0 <command> [args...]" >&2
  exit 1
fi

canonical_path() {
  readlink -f -- "$1"
}

resolve_command_path() {
  local command_name="$1"
  local resolved
  if ! resolved="$(command -v -- "${command_name}" 2>/dev/null)"; then
    return 1
  fi
  canonical_path "${resolved}"
}

resolve_requested_command() {
  local requested="$1"
  if [[ "${requested}" == */* ]]; then
    if [ ! -x "${requested}" ]; then
      return 1
    fi
    canonical_path "${requested}"
    return
  fi
  resolve_command_path "${requested}"
}

allowed_command_name_for_path() {
  local requested_path="$1"
  local command_name allowed_path
  for command_name in "${ALLOWED_COMMAND_NAMES[@]}"; do
    if allowed_path="$(resolve_command_path "${command_name}")" && [ "${requested_path}" = "${allowed_path}" ]; then
      printf '%s\n' "${command_name}"
      return 0
    fi
  done
  return 1
}

# The uplink password reaches nmcli as a passwd-file in the server's memory
# (/proc/<pid>/fd/<fd>, never in argv); refuse any other passwd-file so root
# nmcli cannot be pointed at files on disk.
passwd_file_is_server_memfd() {
  local args=("$@")
  local idx
  for idx in "${!args[@]}"; do
    if [ "${args[${idx}]}" = "passwd-file" ] && \
      ! [[ "${args[$((idx + 1))]:-}" =~ ^/proc/[0-9]+/fd/[0-9]+$ ]]; then
      return 1
    fi
  done
  return 0
}

nmcli_subcommand_allowed() {
  local args=("$@")
  local idx=0
  local token top_level second third
  while [ "${idx}" -lt "${#args[@]}" ]; do
    token="${args[${idx}]}"
    case "${token}" in
      --wait|-f)
        if [ $((idx + 1)) -ge "${#args[@]}" ]; then
          return 1
        fi
        idx=$((idx + 2))
        ;;
      -t)
        idx=$((idx + 1))
        ;;
      *)
        top_level="${token}"
        second="${args[$((idx + 1))]:-}"
        third="${args[$((idx + 2))]:-}"
        case "${top_level}:${second}:${third}" in
          connection:up:*)
            passwd_file_is_server_memfd "${args[@]:$((idx + 3))}"
            return
            ;;
          connection:down:*|connection:delete:*|connection:add:*|connection:modify:*|connection:show:*)
            return 0
            ;;
          device:up:*|dev:wifi:list)
            return 0
            ;;
        esac
        return 1
        ;;
    esac
  done
  return 1
}

invocation_allowed() {
  local command_name="$1"
  shift
  case "${command_name}" in
    nmcli)
      nmcli_subcommand_allowed "$@"
      ;;
    python3)
      [ "$#" -eq 2 ] && [ "$1" = "-c" ] && [ "$2" = "pass" ]
      ;;
    systemctl)
      [ "$#" -eq 2 ] && [ "$1" = "restart" ] && [ "$2" = "vibesensor.service" ]
      ;;
    systemd-run)
      [ "$#" -eq 6 ] && \
        [ "$1" = "--unit" ] && \
        [ "$2" = "vibesensor-post-update-restart" ] && \
        [ "$3" = "--on-active=2s" ] && \
        [ "$4" = "systemctl" ] && \
        [ "$5" = "restart" ] && \
        [ "$6" = "vibesensor.service" ]
      ;;
    *)
      return 1
      ;;
  esac
}

REQUESTED_PATH="$(resolve_requested_command "$1" || true)"
COMMAND_NAME=""
if [ -n "${REQUESTED_PATH}" ]; then
  COMMAND_NAME="$(allowed_command_name_for_path "${REQUESTED_PATH}" || true)"
fi

if [ -z "${COMMAND_NAME}" ] || ! invocation_allowed "${COMMAND_NAME}" "${@:2}"; then
  echo "vibesensor_update_allowlist: command '$1' is not allowed" >&2
  exit 126
fi

exec "${REQUESTED_PATH}" "${@:2}"
