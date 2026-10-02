#!/bin/sh
set -eu

script_dir="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
node "$script_dir/../../tools/ui/ensure_ui_bootstrap.mjs" --log-prefix "[dev:docker]"

exec npm run dev -- "$@"
