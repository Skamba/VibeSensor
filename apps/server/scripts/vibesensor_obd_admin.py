#!/usr/bin/env python3
"""Privileged Bluetooth OBD helper wrapper."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
VENV_ROOT_CANDIDATES = (
    SERVER_ROOT / ".venv",
    SERVER_ROOT.parents[1] / ".venv",
)
VENV_PYTHON_BASENAMES = ("python", "python3")


def _find_repo_venv_python() -> Path | None:
    for root in VENV_ROOT_CANDIDATES:
        for basename in VENV_PYTHON_BASENAMES:
            candidate = root / "bin" / basename
            if candidate.is_file():
                return candidate
    return None


def _running_in_target_venv(target_python: Path) -> bool:
    # On the Pi the venv interpreter can be a symlink to /usr/bin/python3.x, so
    # compare the active Python prefix instead of the resolved executable path.
    return Path(sys.prefix).resolve() == target_python.parent.parent.resolve()


def _ensure_repo_venv_python() -> None:
    target_python = _find_repo_venv_python()
    if target_python is None:
        candidates = ", ".join(
            str(root / "bin" / basename)
            for root in VENV_ROOT_CANDIDATES
            for basename in VENV_PYTHON_BASENAMES
        )
        raise SystemExit(f"Missing expected virtualenv interpreter (checked: {candidates})")
    if _running_in_target_venv(target_python):
        return
    os.execv(
        str(target_python),
        [str(target_python), "-m", "vibesensor.adapters.obd.admin_helper", *sys.argv[1:]],
    )


def main() -> int:
    _ensure_repo_venv_python()
    from vibesensor.adapters.obd.admin_helper import main as helper_main

    return helper_main()


if __name__ == "__main__":
    raise SystemExit(main())
