#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "apps" / "server"


def build_command(min_coverage: int, html: bool, fail_under: bool) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-m",
        "not selenium",
        "--cov=vibesensor",
        "--cov-report=term-missing:skip-covered",
    ]
    if html:
        command.append("--cov-report=html:../../artifacts/coverage/html")
    if fail_under:
        command.append(f"--cov-fail-under={min_coverage}")
    command.append("tests")
    return command


def main() -> int:
    parser = argparse.ArgumentParser(description="Run backend coverage with pytest-cov")
    parser.add_argument(
        "--html",
        action="store_true",
        help="Write an HTML report under artifacts/coverage/html",
    )
    parser.add_argument(
        "--fail-under",
        action="store_true",
        help="Fail when total coverage is below the threshold",
    )
    parser.add_argument(
        "--min-coverage",
        type=int,
        default=80,
        help="Coverage threshold used with --fail-under",
    )
    args = parser.parse_args()

    command = build_command(args.min_coverage, args.html, args.fail_under)
    print("Running coverage command:", " ".join(command))
    return subprocess.run(command, cwd=SERVER_DIR, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
