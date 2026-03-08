#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


def _run(cmd: list[str]) -> int:
    completed = subprocess.run(cmd, cwd=str(ROOT), check=False)
    return int(completed.returncode)


def _build_ci_parity_cmd(args: argparse.Namespace, extra_args: list[str]) -> list[str]:
    cmd = [PYTHON, "tools/tests/run_ci_parallel.py"]
    for job in args.job:
        cmd.extend(["--job", job])
    if args.skip_bootstrap:
        cmd.append("--skip-bootstrap")
    if args.skip_npm_ci:
        cmd.append("--skip-npm-ci")
    cmd.extend(extra_args)
    return cmd


def _build_full_stack_cmd(args: argparse.Namespace, extra_args: list[str]) -> list[str]:
    cmd = [PYTHON, "tools/tests/run_full_suite.py"]
    if args.fast_e2e:
        cmd.append("--fast-e2e")
    if args.skip_ui_sync:
        cmd.append("--skip-ui-sync")
    if args.skip_ui_smoke:
        cmd.append("--skip-ui-smoke")
    if args.skip_unit_tests:
        cmd.append("--skip-unit-tests")
    if args.skip_docker_build:
        cmd.append("--skip-docker-build")
    cmd.extend(extra_args)
    return cmd


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Canonical local verification entry point for VibeSensor.",
    )
    parser.add_argument(
        "--suite",
        choices=("ci-parity", "full-stack"),
        default="ci-parity",
        help="Verification suite to run.",
    )
    parser.add_argument(
        "--job",
        action="append",
        default=[],
        help="Repeatable CI-parity job selection passed through to run_ci_parallel.py.",
    )
    parser.add_argument(
        "--skip-bootstrap",
        action="store_true",
        help="Skip Python/npm bootstrap in ci-parity mode.",
    )
    parser.add_argument(
        "--skip-npm-ci",
        action="store_true",
        help="Skip npm ci during ci-parity bootstrap.",
    )
    parser.add_argument(
        "--fast-e2e",
        action="store_true",
        help="Run only the fast e2e subset in full-stack mode.",
    )
    parser.add_argument(
        "--skip-ui-sync",
        action="store_true",
        help="Skip syncing built UI assets in full-stack mode.",
    )
    parser.add_argument(
        "--skip-ui-smoke",
        action="store_true",
        help="Skip UI smoke tests in full-stack mode.",
    )
    parser.add_argument(
        "--skip-unit-tests",
        action="store_true",
        help="Skip backend unit/integration tests in full-stack mode.",
    )
    parser.add_argument(
        "--skip-docker-build",
        action="store_true",
        help="Reuse an existing docker image in full-stack mode.",
    )
    args, extra_args = parser.parse_known_args()

    if args.suite == "ci-parity":
        return _run(_build_ci_parity_cmd(args, extra_args))
    return _run(_build_full_stack_cmd(args, extra_args))


if __name__ == "__main__":
    raise SystemExit(main())