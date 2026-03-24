#!/bin/sh
set -eu

if command -v sha256sum >/dev/null 2>&1; then
	lock_hash="$(sha256sum package-lock.json | cut -d ' ' -f1)"
elif command -v shasum >/dev/null 2>&1; then
	lock_hash="$(shasum -a 256 package-lock.json | cut -d ' ' -f1)"
else
	echo "[dev:docker] Could not find sha256sum or shasum to hash package-lock.json." >&2
	exit 1
fi

current_lock_hash=""

if [ -f .npm-ci-lock.sha256 ]; then
	current_lock_hash="$(tr -d '\n' < .npm-ci-lock.sha256)"
fi

if [ ! -d node_modules ] || [ "$lock_hash" != "$current_lock_hash" ]; then
	echo "[dev:docker] Running npm ci because node_modules is missing or package-lock.json changed."
	npm ci
	printf '%s\n' "$lock_hash" > .npm-ci-lock.sha256
fi

if npm run check:contracts; then
	:
else
	status=$?
	echo "[dev:docker] Frontend contracts are stale. Run \`make sync-contracts\` or \`npm --prefix apps/ui run sync:contracts\`, then restart the dev stack." >&2
	exit "$status"
fi

exec npm run dev -- "$@"
