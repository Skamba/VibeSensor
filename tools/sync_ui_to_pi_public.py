#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
from pathlib import Path


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build apps/ui and sync dist output into apps/server/public."
    )
    parser.add_argument(
        "--skip-npm-ci",
        action="store_true",
        help="Skip `npm ci` before building.",
    )
    parser.add_argument(
        "--force-npm-ci",
        action="store_true",
        help="Force `npm ci` even when node_modules and lockfile hash are unchanged.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    ui_dir = repo_root / "apps" / "ui"
    dist_dir = ui_dir / "dist"
    public_dir = repo_root / "apps" / "server" / "public"
    lock_file = ui_dir / "package-lock.json"
    lock_hash_file = ui_dir / ".npm-ci-lock.sha256"

    lock_hash = hashlib.sha256(lock_file.read_bytes()).hexdigest()
    previous_lock_hash = lock_hash_file.read_text(encoding="utf-8").strip() if lock_hash_file.exists() else ""

    should_run_npm_ci = (
        not args.skip_npm_ci
        and (
            args.force_npm_ci
            or not (ui_dir / "node_modules").exists()
            or lock_hash != previous_lock_hash
        )
    )

    if should_run_npm_ci:
        _run(["npm", "ci"], cwd=ui_dir)
        lock_hash_file.write_text(lock_hash, encoding="utf-8")
    _run(["npm", "run", "build"], cwd=ui_dir)

    shutil.rmtree(public_dir, ignore_errors=True)
    public_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(dist_dir, public_dir, dirs_exist_ok=True)
    print(f"Synced {dist_dir} -> {public_dir}")


if __name__ == "__main__":
    main()
