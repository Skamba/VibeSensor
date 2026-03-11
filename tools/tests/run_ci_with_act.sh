#!/usr/bin/env bash
# Thin convenience wrapper around `act` for running the CI workflow locally.
# Raw `act` commands are the primary documented interface; this script is
# optional convenience only.
#
# Usage:
#   ./tools/tests/run_ci_with_act.sh              # run all CI jobs (push event)
#   ./tools/tests/run_ci_with_act.sh -l            # list available jobs
#   ./tools/tests/run_ci_with_act.sh -j backend-quality   # run one job
#   ./tools/tests/run_ci_with_act.sh -j backend-tests     # run backend tests
#   ./tools/tests/run_ci_with_act.sh <extra act args>     # pass-through
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# ── prerequisite checks ──────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  echo "Error: Docker is required but not installed." >&2
  exit 1
fi

if ! docker info &>/dev/null 2>&1; then
  echo "Error: Docker daemon is not running." >&2
  exit 1
fi

if ! command -v act &>/dev/null; then
  echo "Error: act is required but not installed." >&2
  echo "Install: https://nektosact.com/installation/index.html" >&2
  exit 1
fi

# ── run act ──────────────────────────────────────────────────────────
cd "$REPO_ROOT"

EVENT_FILE="tools/tests/act-event.json"

ACT_ARGS=(-W .github/workflows/ci.yml -e "$EVENT_FILE")
if [ -f .secrets.act ]; then
  ACT_ARGS+=(--secret-file .secrets.act)
fi

exec act "${ACT_ARGS[@]}" "$@"
