"""Privilege escalation helpers for updater commands."""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "build_privilege_probe_args",
    "build_sudo_args",
]

# ---------------------------------------------------------------------------
# sudo wrapper helpers
# ---------------------------------------------------------------------------

_SOURCE_TREE_WRAPPER_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent / "scripts" / "vibesensor_update_sudo.sh"
)
_DEFAULT_INSTALL_REPO = Path("/opt/VibeSensor")


def _sudo_wrapper_path() -> Path | None:
    """Return the first installed wrapper path that exists on disk."""

    configured_wrapper = os.environ.get("VIBESENSOR_UPDATE_SUDO_WRAPPER", "").strip()
    configured_repo = os.environ.get("VIBESENSOR_REPO_PATH", "").strip()
    candidate_paths = [
        Path(configured_wrapper) if configured_wrapper else None,
        (
            Path(configured_repo) / "apps" / "server" / "scripts" / "vibesensor_update_sudo.sh"
            if configured_repo
            else None
        ),
        _DEFAULT_INSTALL_REPO / "apps" / "server" / "scripts" / "vibesensor_update_sudo.sh",
        _SOURCE_TREE_WRAPPER_SCRIPT,
    ]
    for candidate in candidate_paths:
        if candidate is not None and candidate.is_file():
            return candidate
    return None


def _sudo_prefix() -> list[str]:
    """Return the sudo prefix for privileged commands."""
    if os.geteuid() == 0:
        return []
    wrapper = _sudo_wrapper_path()
    if wrapper is not None:
        return ["sudo", "-n", str(wrapper)]
    return ["sudo", "-n"]


def build_sudo_args(args: list[str]) -> list[str]:
    """Return *args* prefixed for restricted privileged execution."""

    return [*_sudo_prefix(), *args]


def build_privilege_probe_args() -> list[str]:
    """Return a harmless command that exercises the updater's sudo path."""
    return ["python3", "-c", "pass"]
