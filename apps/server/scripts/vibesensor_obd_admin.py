#!/usr/bin/env python3
"""Privileged Bluetooth OBD helper wrapper."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON_CANDIDATES = (
    SERVER_ROOT / ".venv" / "bin" / "python",
    SERVER_ROOT.parents[1] / ".venv" / "bin" / "python",
)


def _ensure_repo_venv_python() -> None:
    current_python = Path(sys.executable).resolve()
    target_python = next((path for path in VENV_PYTHON_CANDIDATES if path.is_file()), None)
    if target_python is None:
        candidates = ", ".join(str(path) for path in VENV_PYTHON_CANDIDATES)
        raise SystemExit(f"Missing expected virtualenv interpreter (checked: {candidates})")
    if current_python == target_python.resolve():
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
