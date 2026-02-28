#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys


def _parse_collected_test_ids(output: str) -> list[str]:
    test_ids: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if "::" not in line:
            continue
        if line.startswith("=") or line.startswith("<"):
            continue
        if line.startswith("tests/"):
            test_ids.append(f"apps/server/{line}")
            continue
        if line.startswith("apps/server/tests/"):
            test_ids.append(line)
    return test_ids


def _collect_test_ids(pytest_args: list[str]) -> list[str]:
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", *pytest_args]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stdout.write(result.stdout or "")
        sys.stderr.write(result.stderr or "")
        raise SystemExit(result.returncode)
    return _parse_collected_test_ids(result.stdout or "")


def _run_shard(selected_test_ids: list[str]) -> int:
    if not selected_test_ids:
        print("[pytest-shard] no tests selected for this shard; exiting 0", flush=True)
        return 0
    cmd = [sys.executable, "-m", "pytest", "-q", *selected_test_ids]
    print(f"[pytest-shard] running {len(selected_test_ids)} tests", flush=True)
    print(f"[pytest-shard] command: {' '.join(cmd[:6])} ...", flush=True)
    result = subprocess.run(cmd, check=False)
    return int(result.returncode)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Collect pytest tests and run a single shard selected by round-robin index."
        )
    )
    parser.add_argument(
        "--shard-index",
        type=int,
        required=True,
        help="1-based shard index to run.",
    )
    parser.add_argument(
        "--shard-count",
        type=int,
        required=True,
        help="Total shard count.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print shard stats without running pytest.",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to pytest collect-only. Prefix with '--' to separate.",
    )
    args = parser.parse_args()
    if args.pytest_args and args.pytest_args[0] == "--":
        args.pytest_args = args.pytest_args[1:]
    if args.shard_count < 1:
        raise SystemExit("--shard-count must be >= 1")
    if not (1 <= args.shard_index <= args.shard_count):
        raise SystemExit("--shard-index must be between 1 and --shard-count")
    return args


def main() -> int:
    args = _parse_args()
    collected = _collect_test_ids(list(args.pytest_args))
    shard_zero_index = args.shard_index - 1
    selected = [
        test_id
        for index, test_id in enumerate(collected)
        if index % args.shard_count == shard_zero_index
    ]

    print(
        "[pytest-shard]"
        f" collected={len(collected)}"
        f" shard={args.shard_index}/{args.shard_count}"
        f" selected={len(selected)}",
        flush=True,
    )

    if args.dry_run:
        for test_id in selected[:10]:
            print(f"[pytest-shard] sample: {test_id}", flush=True)
        return 0

    return _run_shard(selected)


if __name__ == "__main__":
    raise SystemExit(main())
