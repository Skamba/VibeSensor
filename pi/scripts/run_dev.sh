#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="$(cd "${PI_DIR}/.." && pwd)"

cd "${PI_DIR}"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

python -m vibesensor.app --config "${PI_DIR}/config.yaml" &
SERVER_PID=$!

python "${REPO_DIR}/tools/simulator/sim_sender.py" --count 3 --server-host 127.0.0.1 &
SIM_PID=$!

cleanup() {
  kill "${SIM_PID}" >/dev/null 2>&1 || true
  kill "${SERVER_PID}" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

wait "${SERVER_PID}"

