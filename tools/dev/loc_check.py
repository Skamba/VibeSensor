#!/usr/bin/env python3
"""LOC check – enforce H2 file-size heuristics.

Hard cap: 600 LOC for hand-written tracked source files.
Soft cap: 450 LOC (warnings only).

Exit 0 if no hard-cap violations, 1 otherwise.
"""

from __future__ import annotations

import subprocess
import sys

HARD_CAP = 600
SOFT_CAP = 450

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
    hard_violations: list[tuple[str, int]] = []
    soft_violations: list[tuple[str, int]] = []

    for path in files:
        try:
            with open(path) as fh:
                loc = sum(1 for _ in fh)
        except (OSError, UnicodeDecodeError):
            continue
        if loc > HARD_CAP:
            hard_violations.append((path, loc))
        elif loc > SOFT_CAP:
            soft_violations.append((path, loc))

    hard_violations.sort(key=lambda x: -x[1])
    soft_violations.sort(key=lambda x: -x[1])

    if soft_violations:
        print(f"⚠  {len(soft_violations)} file(s) exceed soft cap ({SOFT_CAP} LOC):")
        for path, loc in soft_violations:
            print(f"   {loc:5d}  {path}")

    if hard_violations:
        print(f"❌ {len(hard_violations)} file(s) exceed hard cap ({HARD_CAP} LOC):")
        for path, loc in hard_violations:
            print(f"   {loc:5d}  {path}")
        return 1

    if not soft_violations:
        print(f"✅ All tracked source files within {HARD_CAP} LOC hard cap.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
