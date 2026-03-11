#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from vibesensor.update.status import UI_BUILD_METADATA_FILE, hash_tree


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ui_dir = repo_root / "apps" / "ui"
    dist_dir = ui_dir / "dist"
    static_dir = repo_root / "apps" / "server" / "vibesensor" / "static"
    lock_file = ui_dir / "package-lock.json"
    lock_hash_file = ui_dir / ".npm-ci-lock.sha256"

    lock_hash = hashlib.sha256(lock_file.read_bytes()).hexdigest()
    previous_lock_hash = (
        lock_hash_file.read_text(encoding="utf-8").strip()
        if lock_hash_file.exists()
        else ""
    )

    should_run_npm_ci = (
        not (ui_dir / "node_modules").exists() or lock_hash != previous_lock_hash
    )

    if should_run_npm_ci:
        _run(["npm", "ci"], cwd=ui_dir)
        lock_hash_file.write_text(lock_hash, encoding="utf-8")
    _run(["npm", "run", "typecheck"], cwd=ui_dir)
    _run(["npm", "run", "build"], cwd=ui_dir)

    shutil.rmtree(static_dir, ignore_errors=True)
    static_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(dist_dir, static_dir, dirs_exist_ok=True)
    ui_source_hash = hash_tree(
        ui_dir,
        ignore_names={"node_modules", "dist", ".git", ".npm-ci-lock.sha256"},
    )
    static_assets_hash = hash_tree(static_dir, ignore_names={UI_BUILD_METADATA_FILE})
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
    (static_dir / UI_BUILD_METADATA_FILE).write_text(
        json.dumps(
            {
                "ui_source_hash": ui_source_hash,
                "static_assets_hash": static_assets_hash,
                "git_commit": git_commit,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Synced {dist_dir} -> {static_dir}")


if __name__ == "__main__":
    main()
