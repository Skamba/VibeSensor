#!/usr/bin/env bash
# Thin convenience wrapper around `act` for running the CI workflow locally.
# Raw `act` commands are the primary documented interface; this script is
# optional convenience only.
#
# Usage:
#   ./tools/tests/run_ci_with_act.sh              # run changed-scope CI jobs (pull_request event)
#   ./tools/tests/run_ci_with_act.sh --full-stack # force all CI jobs through ci-scope
#   ./tools/tests/run_ci_with_act.sh -l            # list available jobs
#   ./tools/tests/run_ci_with_act.sh -j backend-lint      # run one job
#   ./tools/tests/run_ci_with_act.sh -j backend-tests-1   # run one backend test shard
#   ./tools/tests/run_ci_with_act.sh --base-ref main -j backend-lint
#   ./tools/tests/run_ci_with_act.sh <extra act args>     # pass-through
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BASE_REF=""
FULL_STACK=0
PASSTHROUGH_ARGS=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --base-ref)
      if [ "$#" -lt 2 ]; then
        echo "Error: --base-ref requires a value." >&2
        exit 2
      fi
      BASE_REF="$2"
      shift 2
      ;;
    --base-ref=*)
      BASE_REF="${1#--base-ref=}"
      shift
      ;;
    --scope-from-diff)
      FULL_STACK=0
      shift
      ;;
    --full-stack)
      FULL_STACK=1
      shift
      ;;
    *)
      PASSTHROUGH_ARGS+=("$1")
      shift
      ;;
  esac
done

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

EVENT_FILE="$(mktemp "${TMPDIR:-/tmp}/vibesensor-act-event.XXXXXX.json")"
cleanup() {
  rm -f "$EVENT_FILE"
}
trap cleanup EXIT

GENERATE_ARGS=(--output "$EVENT_FILE")
if [ -n "$BASE_REF" ]; then
  GENERATE_ARGS+=(--base-ref "$BASE_REF")
fi
"${PYTHON:-python3}" tools/tests/act_event.py "${GENERATE_ARGS[@]}"

ACT_ARGS=(pull_request -W .github/workflows/ci.yml -e "$EVENT_FILE")
if [ "$FULL_STACK" -eq 1 ]; then
  ACT_ARGS+=(--env VIBESENSOR_CI_FORCE_FULL_STACK=1)
fi
if [ -f .secrets.act ]; then
  ACT_ARGS+=(--secret-file .secrets.act)
fi

act "${ACT_ARGS[@]}" "${PASSTHROUGH_ARGS[@]}"
