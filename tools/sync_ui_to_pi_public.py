#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ui/ and sync dist output into pi/public.")
    parser.add_argument(
        "--skip-npm-ci",
        action="store_true",
        help="Skip `npm ci` before building.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    ui_dir = repo_root / "ui"
    dist_dir = ui_dir / "dist"
    public_dir = repo_root / "pi" / "public"

    if not args.skip_npm_ci:
        _run(["npm", "ci"], cwd=ui_dir)
    _run(["npm", "run", "build"], cwd=ui_dir)

    shutil.rmtree(public_dir, ignore_errors=True)
    public_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(dist_dir, public_dir, dirs_exist_ok=True)
    print(f"Synced {dist_dir} -> {public_dir}")


if __name__ == "__main__":
    main()
