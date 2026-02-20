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

import subprocess
import sys

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
}

# Data files that are intentionally large (JSON extracted from code)
EXCLUDE_FILES: set[str] = set()


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()


def _should_check(path: str) -> bool:
    import os

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
    files = [f for f in _tracked_files() if _should_check(f)]
    measured: list[tuple[str, int]] = []

    for path in files:
        try:
            with open(path) as fh:
                loc = sum(1 for _ in fh)
        except (OSError, UnicodeDecodeError):
            continue
        measured.append((path, loc))

    measured.sort(key=lambda item: (-item[1], item[0]))

    print(
        "ℹ️  File-length advisory: keep files short where practical, "
        "without hurting human maintainability."
    )
    print(f"Showing top {min(TOP_N, len(measured))} longest tracked source files:")
    for path, loc in measured[:TOP_N]:
        print(f"   {loc:5d}  {path}")

    print(
        "\nSuggestion: refactor large files when it improves clarity; "
        "avoid artificial splits that make maintenance harder."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
