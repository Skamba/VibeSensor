# ruff: noqa: F403,F405
"""Basic repository hygiene checks."""

from __future__ import annotations

import subprocess
from pathlib import Path


from ._shared import *


def _git_tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=False,
    ).stdout
    return [ROOT / p.decode("utf-8", errors="replace") for p in out.split(b"\x00") if p]


def check_line_endings() -> list[str]:
    offenders: list[str] = []
    for path in _git_tracked_files():
        if path.suffix.lower() not in TEXT_EXTS:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\r\n" in data:
            offenders.append(str(path.relative_to(ROOT)))
    return offenders


def _is_pointer_file(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return len(lines) == 1 and bool(_RELATIVE_POINTER_RE.fullmatch(lines[0]))


def check_path_indirections() -> tuple[list[str], list[str]]:
    pointer_files: list[str] = []
    python_path_hacks: list[str] = []
    for path in _git_tracked_files():
        if ".git" in path.parts:
            continue
        rel = str(path.relative_to(ROOT))
        if _is_pointer_file(path):
            pointer_files.append(rel)
        if path.suffix == ".py" and rel not in {
            "tools/dev/check_hygiene.py",
            "tools/dev/hygiene/checks.py",
        }:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if _PY_PATH_HACK_RE.search(text):
                python_path_hacks.append(rel)
    return pointer_files, python_path_hacks
