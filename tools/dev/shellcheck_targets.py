#!/usr/bin/env python3
"""Discover tracked shell scripts and templates covered by ShellCheck."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHELLCHECK_ALLOWLIST: dict[str, str] = {}
_SHELL_SUFFIXES = (".sh", ".sh.template")
_SHELL_SHEBANG_RE = re.compile(r"^#!.*\b(?:ba|da|k|z)?sh\b")


def _git_lines(*args: str) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return tuple(line for line in result.stdout.splitlines() if line.strip())


def _tracked_files() -> tuple[str, ...]:
    return _git_lines("ls-files")


def _tracked_executable_files() -> set[str]:
    executable: set[str] = set()
    for line in _git_lines("ls-files", "--stage"):
        metadata, _, path = line.partition("\t")
        mode = metadata.split(maxsplit=1)[0]
        if mode == "100755":
            executable.add(path)
    return executable


def _has_shell_shebang(path: Path) -> bool:
    try:
        first_line = path.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
    except (IndexError, OSError):
        return False
    return _SHELL_SHEBANG_RE.search(first_line) is not None


def shellcheck_targets() -> tuple[str, ...]:
    executable = _tracked_executable_files()
    targets: list[str] = []
    for rel_path in _tracked_files():
        if rel_path in SHELLCHECK_ALLOWLIST:
            continue
        path = ROOT / rel_path
        if not path.is_file():
            continue
        if (
            rel_path.startswith(".githooks/")
            or rel_path.endswith(_SHELL_SUFFIXES)
            or (rel_path in executable and _has_shell_shebang(path))
        ):
            targets.append(rel_path)
    return tuple(sorted(targets))


def main() -> None:
    for rel_path in shellcheck_targets():
        print(rel_path)


if __name__ == "__main__":
    main()
