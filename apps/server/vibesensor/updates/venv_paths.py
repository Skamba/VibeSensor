"""Shared path helpers for the updater reinstall virtual environment."""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "is_reinstall_venv_ready",
    "reinstall_python_executable",
    "reinstall_venv_config_path",
    "reinstall_venv_python_path",
]


def reinstall_venv_python_path(repo: Path) -> Path:
    """Return the updater reinstall venv's expected Python interpreter path."""

    return repo / "apps" / "server" / ".venv" / "bin" / "python3"


def reinstall_venv_config_path(repo: Path) -> Path:
    """Return the updater reinstall venv's ``pyvenv.cfg`` path."""

    return repo / "apps" / "server" / ".venv" / "pyvenv.cfg"


def is_reinstall_venv_ready(repo: Path) -> bool:
    """Report whether the reinstall venv looks executable and configured."""

    venv_python = reinstall_venv_python_path(repo)
    if not (venv_python.is_file() and os.access(venv_python, os.X_OK)):
        return False
    return reinstall_venv_config_path(repo).is_file()


def reinstall_python_executable(repo: Path) -> str:
    """Return the string form expected by subprocess-based installer calls."""

    return str(reinstall_venv_python_path(repo))
