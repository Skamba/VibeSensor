#!/usr/bin/env bash
# Install this checkout's root side on a VibeSensor Pi over SSH.
#
# Usage (on your computer, not on the Pi): push_root_side.sh [user@]host
#   e.g. apps/server/scripts/push_root_side.sh pi@10.4.0.1
#
# For prebuilt-image devices, whose /opt/VibeSensor tree comes from the image
# and is not a git clone. Run it from a checkout of the release the Pi runs.
# The root side is root-helpers/, scripts/ and systemd/
# (docs/operational-runbooks.md, "Installing a release's root side").
#
# The files reach the Pi through a staging directory that the SSH user (the
# service user) can write. So root first copies them into a private directory
# and checks that copy against the manifest digest computed here, from your
# checkout. Only then does it put them in /opt/VibeSensor/apps/server and run
# install_systemd_units.sh. A file changed in transit stops the install
# before root runs anything from it. The digest uses the same manifest as
# install_systemd_units.sh and vibesensor/common/root_side.py.
# Asks for the pi password (SSH, unless you use a key) and for sudo.
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 [user@]host" >&2
  exit 2
fi
TARGET="$1"
SERVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGING=/tmp/vibesensor-root-side

if command -v sha256sum >/dev/null 2>&1; then
  SHA256=(sha256sum)
else
  SHA256=(shasum -a 256) # macOS
fi
cd "${SERVER_DIR}"
DIGEST="$(
  find root-helpers scripts systemd -maxdepth 1 -type f -exec "${SHA256[@]}" {} + |
    LC_ALL=C sort | "${SHA256[@]}" | cut -c1-64
)"
echo "Root side digest of ${SERVER_DIR}: ${DIGEST}"

# Runs as root on the Pi, as "sh -c" with the digest as $1. Keep it free of
# single quotes: it travels inside single quotes in the ssh command line.
# shellcheck disable=SC2016  # expanded by the remote sh, not here
REMOTE_SCRIPT='set -eu
staging=/tmp/vibesensor-root-side
server=/opt/VibeSensor/apps/server
private=$(mktemp -d)
trap "rm -rf \"$private\"" EXIT
# Swapping a checked tree before root runs it needs write access to one of
# these directories, so only a root-owned tree is safe to install from.
for dir in /opt /opt/VibeSensor /opt/VibeSensor/apps "$server"; do
  if [ -n "$(find "$dir" -maxdepth 0 \( ! -user root -o -perm /022 \) -print)" ]; then
    echo "push_root_side: $dir is writable by a non-root user; on a git install run install_systemd_units.sh from the clone instead." >&2
    exit 1
  fi
done
cp -R "$staging/root-helpers" "$staging/scripts" "$staging/systemd" "$private/"
rm -rf "$staging"
cd "$private"
actual=$(find root-helpers scripts systemd -maxdepth 1 -type f -exec sha256sum {} + | LC_ALL=C sort | sha256sum | cut -c1-64)
if [ "$actual" != "$1" ]; then
  echo "push_root_side: the files on the Pi do not match your checkout (digest $actual, expected $1). Nothing was installed." >&2
  exit 1
fi
for dir in root-helpers scripts systemd; do
  rm -rf "$server/$dir"
  mv "$private/$dir" "$server/$dir"
  chmod 0755 "$server/$dir"
done
# The one-time migration drop-in (docs/operational-runbooks.md), if present.
rm -f /run/systemd/system/vibesensor.service.d/migrate.conf
"$server/scripts/install_systemd_units.sh"'

echo "Copying the root side to ${TARGET}:${STAGING}"
find root-helpers scripts systemd -maxdepth 1 -type f -print0 |
  COPYFILE_DISABLE=1 tar --null -T - -cf - |
  ssh "${TARGET}" "rm -rf ${STAGING} && mkdir -m 0700 ${STAGING} && tar -xf - -C ${STAGING}"
echo "Checking and installing it as root on ${TARGET}"
ssh -t "${TARGET}" "sudo /bin/sh -c '${REMOTE_SCRIPT}' push_root_side ${DIGEST}"
