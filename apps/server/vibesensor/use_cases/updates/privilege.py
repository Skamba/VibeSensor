"""Privilege escalation helpers for updater commands."""

from __future__ import annotations

from pathlib import Path

from vibesensor.shared.process_settings import (
    DEFAULT_UPDATE_REPO_PATH,
    load_update_env_settings,
)

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
_DEFAULT_INSTALL_REPO = DEFAULT_UPDATE_REPO_PATH


def _sudo_wrapper_path() -> Path | None:
    """Return the first installed wrapper path that exists on disk."""
    env_settings = load_update_env_settings()
    configured_wrapper = env_settings.update_sudo_wrapper
    configured_repo = env_settings.repo_path
    candidate_paths = [
        configured_wrapper,
        configured_repo / "apps" / "server" / "scripts" / "vibesensor_update_sudo.sh",
        _DEFAULT_INSTALL_REPO / "apps" / "server" / "scripts" / "vibesensor_update_sudo.sh",
        _SOURCE_TREE_WRAPPER_SCRIPT,
    ]
    for candidate in candidate_paths:
        if candidate is not None and candidate.is_file():
            return candidate
    return None


def _sudo_prefix() -> list[str]:
    """Return the sudo prefix for privileged commands."""
    import os

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
