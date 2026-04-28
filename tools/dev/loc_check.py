#!/usr/bin/env python3
"""File-length advisory for maintainability.

This script intentionally does not enforce LoC limits.
It reports the longest tracked source files as a refactoring signal only.

Guidance:
- Keep files short where practical.
- Do not split files mechanically when doing so hurts readability,
  discoverability, or long-term maintainability.

Exit code is always 0.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TOP_N = 25

# Extensions considered hand-written source
SOURCE_EXTS = {".py", ".ts", ".js", ".sh", ".c", ".cpp", ".h"}

# Paths always excluded (build outputs, deps, generated)
EXCLUDE_DIRS = {
    "node_modules",
    ".pio",
    "dist",
    "__pycache__",
    ".cache",
    "artifacts",
    ".venv",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
}

# Data files that are intentionally large (JSON extracted from code)
EXCLUDE_FILES: set[str] = set()


def _walk_files(repo_root: Path) -> list[str]:
    files: list[str] = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        files.append(rel.as_posix())
    return files


def _tracked_files(repo_root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--cached"],
            capture_output=True,
            text=True,
            check=True,
        )
        tracked = [line for line in result.stdout.splitlines() if line]
        if tracked:
            return tracked
    except (OSError, subprocess.CalledProcessError):
        pass
    return _walk_files(repo_root)


def _should_check(path: str) -> bool:
    _, ext = os.path.splitext(path)
    if ext not in SOURCE_EXTS:
        return False
    parts = path.split("/")
    for part in parts:
        if part in EXCLUDE_DIRS:
            return False
    if path in EXCLUDE_FILES:
        return False
    return True


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    files = [f for f in _tracked_files(repo_root) if _should_check(f)]
    measured: list[tuple[str, int]] = []

    for path in files:
        try:
            with open(repo_root / path) as fh:
                loc = sum(1 for _ in fh)
        except (OSError, UnicodeDecodeError):
            continue
        measured.append((path, loc))

    measured.sort(key=lambda item: (-item[1], item[0]))

    print(
        "ℹ️  File-length advisory: keep files short where practical, "
        "without hurting human maintainability."
    )
    print(f"Showing top {min(TOP_N, len(measured))} longest source files:")
    for path, loc in measured[:TOP_N]:
        print(f"   {loc:5d}  {path}")

    print(
        "\nSuggestion: refactor large files when it improves clarity; "
        "avoid artificial splits that make maintenance harder."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
