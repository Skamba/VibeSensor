#!/usr/bin/env python3
"""Build and sync the UI static assets into the server package.

This script is intentionally self-contained — it must run without the
``vibesensor`` package installed (e.g. in the Release-smoke CI job that
runs *before* ``pip install``).  Do not import from ``vibesensor`` here.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

# Keep in sync with vibesensor.use_cases.updates.status.UI_BUILD_METADATA_FILE
UI_BUILD_METADATA_FILE = ".vibesensor-ui-build.json"


def _hash_tree(root: Path, *, ignore_names: set[str]) -> str:
    """Deterministic SHA-256 of a directory tree (sorted, filtered).

    Canonical copy lives in ``vibesensor.use_cases.updates.status.hash_tree``; this
    local duplicate exists so the script stays self-contained.
    """
    if not root.exists():
        return ""
    hasher = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root)
        if any(part in ignore_names for part in relative.parts):
            continue
        hasher.update(str(relative.as_posix()).encode("utf-8"))
        hasher.update(b"\0")
        try:
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(65536)
                    if not chunk:
                        break
                    hasher.update(chunk)
        except OSError:
            continue
        hasher.update(b"\0")
    return hasher.hexdigest()


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
    ui_source_hash = _hash_tree(
        ui_dir,
        ignore_names={"node_modules", "dist", ".git", ".npm-ci-lock.sha256"},
    )
    static_assets_hash = _hash_tree(static_dir, ignore_names={UI_BUILD_METADATA_FILE})
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
