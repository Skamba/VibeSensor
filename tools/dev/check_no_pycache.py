#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _find_forbidden_tracked_paths() -> list[str] | None:
    result = subprocess.run(
        ["git", "ls-files", "--cached"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return [
        line
        for line in result.stdout.splitlines()
        if "__pycache__/" in line or line.endswith(".pyc")
    ]


def _find_forbidden_paths_in_filesystem(root: Path) -> list[str]:
    excluded_dirs = {
        ".git",
        ".venv",
        ".pytest_cache",
        ".ruff_cache",
        ".cache",
        "node_modules",
        "dist",
        "artifacts",
    }
    bad: list[str] = []
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in excluded_dirs]
        current_path = Path(current_root)
        for filename in filenames:
            file_path = current_path / filename
            rel_path = file_path.relative_to(root).as_posix()
            if file_path.suffix == ".pyc" or "__pycache__" in file_path.parts:
                bad.append(rel_path)
    return bad


def main() -> int:
    bad = _find_forbidden_tracked_paths()
    if bad is None:
        bad = _find_forbidden_paths_in_filesystem(Path.cwd())
    if bad:
        print("Found forbidden Python cache artifacts:")
        for path in bad:
            print(path)
        return 1
    print("No tracked __pycache__/ or .pyc artifacts found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
