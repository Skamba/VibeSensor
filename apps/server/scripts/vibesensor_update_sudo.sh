#!/usr/bin/env bash
# Restricted sudo wrapper for VibeSensor system update.
# Only allows a whitelist of commands that the update process needs.
# Install via: sudo cp scripts/vibesensor_update_sudo.sh /usr/local/bin/
# Add to sudoers: vibesensor ALL=(root) NOPASSWD: /usr/local/bin/vibesensor_update_sudo.sh
set -euo pipefail

ALLOWED_CMDS=(
  "nmcli"
  "git"
  "python3"
  "systemd-run"
  "systemctl"
  "timeout"
  "rfkill"
)

if [ $# -lt 1 ]; then
  echo "Usage: $0 <command> [args...]" >&2
  exit 1
fi

CMD_BASE="$(basename "$1")"
ALLOWED=0
for acmd in "${ALLOWED_CMDS[@]}"; do
  if [ "${CMD_BASE}" = "${acmd}" ]; then
    ALLOWED=1
    break
  fi
done

if [ "${ALLOWED}" -ne 1 ]; then
  echo "vibesensor_update_sudo: command '${CMD_BASE}' is not allowed" >&2
  exit 126
fi

exec "$@"
