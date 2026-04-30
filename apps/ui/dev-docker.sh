#!/bin/sh
set -eu

script_dir="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
bootstrap_helper="$script_dir/../../tools/ui/ensure_ui_bootstrap.mjs"

node "$bootstrap_helper" --log-prefix "[dev:docker]"

if npm run sync:generated-contracts; then
	:
else
	status=$?
	echo "[dev:docker] Could not regenerate the frontend contract derivatives. Run \`make sync-contracts\` or \`npm --prefix apps/ui run sync:contracts\`, then restart the dev stack." >&2
	exit "$status"
fi

exec npm run dev -- "$@"
