"""Typed process-level settings for startup/static backend configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    "WebSocketEnvSettings",
    "export_config_path_env",
    "load_bootstrap_env_settings",
    "load_update_env_settings",
    "load_websocket_env_settings",
    "summarize_process_settings",
]

CONFIG_PATH_ENV = "VIBESENSOR_CONFIG_PATH"
SERVE_STATIC_ENV = "VIBESENSOR_SERVE_STATIC"
WS_DEBUG_ENV = "VIBESENSOR_WS_DEBUG"
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
DEFAULT_FIRMWARE_CHANNEL: Literal["stable", "prerelease"] = "stable"


class _EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        env_ignore_empty=True,
        str_strip_whitespace=True,
    )


class BootstrapEnvSettings(_EnvSettings):
    """Typed startup env settings used by bootstrap and reload wiring."""

    config_path: Path | None = Field(default=None, validation_alias=CONFIG_PATH_ENV)
    serve_static: bool = Field(default=True, validation_alias=SERVE_STATIC_ENV)

    @field_validator("config_path", mode="after")
    @classmethod
    def _expand_config_path(cls, value: Path | None) -> Path | None:
        return value.expanduser() if value is not None else None


class WebSocketEnvSettings(_EnvSettings):
    """Typed runtime env settings for the WebSocket debug flag."""

    ws_debug: bool = Field(default=False, validation_alias=WS_DEBUG_ENV)


class UpdateEnvSettings(_EnvSettings):
    """Typed env settings for updater/release runtime overrides."""

    repo_path: Path = Field(default=DEFAULT_UPDATE_REPO_PATH, validation_alias=UPDATE_REPO_PATH_ENV)
    rollback_dir: Path = Field(
        default=DEFAULT_UPDATE_ROLLBACK_DIR,
        validation_alias=UPDATE_ROLLBACK_DIR_ENV,
    )
    update_state_path: Path = Field(
        default=DEFAULT_UPDATE_STATE_PATH,
        validation_alias=UPDATE_STATE_PATH_ENV,
    )
    update_sudo_wrapper: Path | None = Field(
        default=None,
        validation_alias=UPDATE_SUDO_WRAPPER_ENV,
    )
    firmware_cache_dir: Path = Field(
        default=DEFAULT_FIRMWARE_CACHE_DIR,
        validation_alias=FIRMWARE_CACHE_DIR_ENV,
    )
    firmware_repo: str = Field(default=GITHUB_REPO, validation_alias=FIRMWARE_REPO_ENV)
    firmware_channel: Literal["stable", "prerelease"] = Field(
        default=DEFAULT_FIRMWARE_CHANNEL,
        validation_alias=FIRMWARE_CHANNEL_ENV,
    )
    firmware_pinned_tag: str = Field(default="", validation_alias=FIRMWARE_PINNED_TAG_ENV)
    server_repo: str = Field(default=GITHUB_REPO, validation_alias=SERVER_REPO_ENV)
    github_token: str = Field(default="", validation_alias=GITHUB_TOKEN_ENV)

    @field_validator(
        "repo_path",
        "rollback_dir",
        "update_state_path",
        "update_sudo_wrapper",
        "firmware_cache_dir",
        mode="after",
    )
    @classmethod
    def _expand_paths(cls, value: Path | None) -> Path | None:
        return value.expanduser() if value is not None else None


def load_bootstrap_env_settings() -> BootstrapEnvSettings:
    return BootstrapEnvSettings()


def load_websocket_env_settings() -> WebSocketEnvSettings:
    return WebSocketEnvSettings()


def load_update_env_settings() -> UpdateEnvSettings:
    return UpdateEnvSettings()


def export_config_path_env(config_path: Path | None) -> None:
    """Export or clear the reload-mode config path override."""

    if config_path is None:
        os.environ.pop(CONFIG_PATH_ENV, None)
        return
    os.environ[CONFIG_PATH_ENV] = str(config_path.expanduser().resolve())


def summarize_process_settings() -> dict[str, object]:
    """Return a safe summary of env/process settings for preflight output."""

    bootstrap = load_bootstrap_env_settings()
    websocket = load_websocket_env_settings()
    update = load_update_env_settings()
    return {
        "config_path_override": str(bootstrap.config_path) if bootstrap.config_path else None,
        "serve_static": bootstrap.serve_static,
        "ws_debug": websocket.ws_debug,
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
