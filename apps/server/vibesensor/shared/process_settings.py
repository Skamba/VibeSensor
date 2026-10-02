"""Typed process-level settings for startup/static backend configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from vibesensor.shared.constants.github import GITHUB_REPO

__all__ = [
    "CONFIG_PATH_ENV",
    "DEFAULT_FIRMWARE_CACHE_DIR",
    "DEFAULT_FIRMWARE_CHANNEL",
    "DEFAULT_UPDATE_REPO_PATH",
    "DEFAULT_UPDATE_ROLLBACK_DIR",
    "DEFAULT_UPDATE_STATE_PATH",
    "BootstrapEnvSettings",
    "UpdateEnvSettings",
    "export_config_path_env",
    "load_bootstrap_env_settings",
    "load_update_env_settings",
    "summarize_process_settings",
]

CONFIG_PATH_ENV = "VIBESENSOR_CONFIG_PATH"
SERVE_STATIC_ENV = "VIBESENSOR_SERVE_STATIC"
UPDATE_REPO_PATH_ENV = "VIBESENSOR_REPO_PATH"
UPDATE_ROLLBACK_DIR_ENV = "VIBESENSOR_ROLLBACK_DIR"
UPDATE_STATE_PATH_ENV = "VIBESENSOR_UPDATE_STATE_PATH"
UPDATE_SUDO_WRAPPER_ENV = "VIBESENSOR_UPDATE_SUDO_WRAPPER"
FIRMWARE_CACHE_DIR_ENV = "VIBESENSOR_FIRMWARE_CACHE_DIR"
FIRMWARE_REPO_ENV = "VIBESENSOR_FIRMWARE_REPO"
FIRMWARE_CHANNEL_ENV = "VIBESENSOR_FIRMWARE_CHANNEL"
FIRMWARE_PINNED_TAG_ENV = "VIBESENSOR_FIRMWARE_PINNED_TAG"
SERVER_REPO_ENV = "VIBESENSOR_SERVER_REPO"
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"

DEFAULT_UPDATE_REPO_PATH = Path("/opt/VibeSensor")
DEFAULT_UPDATE_ROLLBACK_DIR = Path("/var/lib/vibesensor/rollback")
DEFAULT_UPDATE_STATE_PATH = Path("/var/lib/vibesensor/update/update_status.json")
DEFAULT_FIRMWARE_CACHE_DIR = Path("/var/lib/vibesensor/firmware")
FirmwareChannel = Literal["stable", "prerelease"]
DEFAULT_FIRMWARE_CHANNEL: FirmwareChannel = "stable"

_TRUE_VALUES = frozenset({"1", "on", "t", "true", "y", "yes"})
_FALSE_VALUES = frozenset({"0", "off", "f", "false", "n", "no"})


def _env_raw(name: str) -> str | None:
    """Return the env value, treating unset and empty values as absent."""

    value = os.environ.get(name)
    return value or None


def _env_str(name: str, default: str) -> str:
    raw = _env_raw(name)
    return default if raw is None else raw.strip()


def _env_path(name: str, default: Path) -> Path:
    raw = _env_raw(name)
    return default if raw is None else Path(raw.strip()).expanduser()


def _env_optional_path(name: str) -> Path | None:
    raw = _env_raw(name)
    return None if raw is None else Path(raw.strip()).expanduser()


def _env_bool(name: str, default: bool) -> bool:
    raw = _env_raw(name)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    raise ValueError(f"{name}: expected a boolean (1/0, true/false, yes/no, on/off), got {raw!r}")


def _env_firmware_channel(name: str) -> FirmwareChannel:
    raw = _env_raw(name)
    if raw is None:
        return DEFAULT_FIRMWARE_CHANNEL
    if raw == "stable":
        return "stable"
    if raw == "prerelease":
        return "prerelease"
    raise ValueError(f"{name}: expected 'stable' or 'prerelease', got {raw!r}")


@dataclass(frozen=True, slots=True)
class BootstrapEnvSettings:
    """Typed startup env settings used by bootstrap and reload wiring."""

    config_path: Path | None = None
    serve_static: bool = True


@dataclass(frozen=True, slots=True)
class UpdateEnvSettings:
    """Typed env settings for updater/release runtime overrides."""

    repo_path: Path = DEFAULT_UPDATE_REPO_PATH
    rollback_dir: Path = DEFAULT_UPDATE_ROLLBACK_DIR
    update_state_path: Path = DEFAULT_UPDATE_STATE_PATH
    update_sudo_wrapper: Path | None = None
    firmware_cache_dir: Path = DEFAULT_FIRMWARE_CACHE_DIR
    firmware_repo: str = GITHUB_REPO
    firmware_channel: FirmwareChannel = DEFAULT_FIRMWARE_CHANNEL
    firmware_pinned_tag: str = ""
    server_repo: str = GITHUB_REPO
    github_token: str = ""


def load_bootstrap_env_settings() -> BootstrapEnvSettings:
    return BootstrapEnvSettings(
        config_path=_env_optional_path(CONFIG_PATH_ENV),
        serve_static=_env_bool(SERVE_STATIC_ENV, True),
    )


def load_update_env_settings() -> UpdateEnvSettings:
    return UpdateEnvSettings(
        repo_path=_env_path(UPDATE_REPO_PATH_ENV, DEFAULT_UPDATE_REPO_PATH),
        rollback_dir=_env_path(UPDATE_ROLLBACK_DIR_ENV, DEFAULT_UPDATE_ROLLBACK_DIR),
        update_state_path=_env_path(UPDATE_STATE_PATH_ENV, DEFAULT_UPDATE_STATE_PATH),
        update_sudo_wrapper=_env_optional_path(UPDATE_SUDO_WRAPPER_ENV),
        firmware_cache_dir=_env_path(FIRMWARE_CACHE_DIR_ENV, DEFAULT_FIRMWARE_CACHE_DIR),
        firmware_repo=_env_str(FIRMWARE_REPO_ENV, GITHUB_REPO),
        firmware_channel=_env_firmware_channel(FIRMWARE_CHANNEL_ENV),
        firmware_pinned_tag=_env_str(FIRMWARE_PINNED_TAG_ENV, ""),
        server_repo=_env_str(SERVER_REPO_ENV, GITHUB_REPO),
        github_token=_env_str(GITHUB_TOKEN_ENV, ""),
    )


def export_config_path_env(config_path: Path | None) -> None:
    """Export or clear the reload-mode config path override."""

    if config_path is None:
        os.environ.pop(CONFIG_PATH_ENV, None)
        return
    os.environ[CONFIG_PATH_ENV] = str(config_path.expanduser().resolve())


def summarize_process_settings() -> dict[str, object]:
    """Return a safe summary of env/process settings for preflight output."""

    bootstrap = load_bootstrap_env_settings()
    update = load_update_env_settings()
    return {
        "config_path_override": str(bootstrap.config_path) if bootstrap.config_path else None,
        "serve_static": bootstrap.serve_static,
        "repo_path": str(update.repo_path),
        "rollback_dir": str(update.rollback_dir),
        "update_state_path": str(update.update_state_path),
        "update_sudo_wrapper": (
            str(update.update_sudo_wrapper) if update.update_sudo_wrapper else None
        ),
        "firmware_cache_dir": str(update.firmware_cache_dir),
        "firmware_repo": update.firmware_repo,
        "firmware_channel": update.firmware_channel,
        "firmware_pinned_tag": update.firmware_pinned_tag,
        "server_repo": update.server_repo,
        "github_token_configured": bool(update.github_token),
    }
