#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

UI_BUILD_METADATA_FILE = ".vibesensor-ui-build.json"


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def _hash_tree(root: Path, *, ignore_names: set[str]) -> str:
    hasher = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root)
        if any(part in ignore_names for part in relative.parts):
            continue
        hasher.update(str(relative.as_posix()).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


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
    ui_source_hash = _hash_tree(
        ui_dir,
        ignore_names={"node_modules", "dist", ".git", ".npm-ci-lock.sha256"},
    )
    public_assets_hash = _hash_tree(public_dir, ignore_names={UI_BUILD_METADATA_FILE})
    git_commit = (
        subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if (repo_root / ".git").exists()
        else ""
    )
    (public_dir / UI_BUILD_METADATA_FILE).write_text(
        json.dumps(
            {
                "ui_source_hash": ui_source_hash,
                "public_assets_hash": public_assets_hash,
                "git_commit": git_commit,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Synced {dist_dir} -> {public_dir}")


if __name__ == "__main__":
    main()
