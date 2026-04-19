"""Typed env/process settings coverage for backend startup configuration."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from vibesensor.app.settings import (
    DEFAULT_FIRMWARE_CACHE_DIR,
    DEFAULT_UPDATE_REPO_PATH,
    DEFAULT_UPDATE_ROLLBACK_DIR,
    DEFAULT_UPDATE_STATE_PATH,
    BootstrapEnvSettings,
    UpdateEnvSettings,
    WebSocketEnvSettings,
    summarize_process_settings,
)


def _clear_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "VIBESENSOR_CONFIG_PATH",
        "VIBESENSOR_SERVE_STATIC",
        "VIBESENSOR_WS_DEBUG",
        "VIBESENSOR_REPO_PATH",
        "VIBESENSOR_ROLLBACK_DIR",
        "VIBESENSOR_UPDATE_STATE_PATH",
        "VIBESENSOR_UPDATE_SUDO_WRAPPER",
        "VIBESENSOR_FIRMWARE_CACHE_DIR",
        "VIBESENSOR_FIRMWARE_REPO",
        "VIBESENSOR_FIRMWARE_CHANNEL",
        "VIBESENSOR_FIRMWARE_PINNED_TAG",
        "VIBESENSOR_SERVER_REPO",
        "GITHUB_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


def test_bootstrap_env_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_backend_env(monkeypatch)

    settings = BootstrapEnvSettings()

    assert settings.config_path is None
    assert settings.serve_static is True


def test_bootstrap_env_settings_accept_env_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_backend_env(monkeypatch)
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("VIBESENSOR_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("VIBESENSOR_SERVE_STATIC", "0")

    settings = BootstrapEnvSettings()

    assert settings.config_path == config_path
    assert settings.serve_static is False


def test_websocket_env_settings_reject_invalid_bool(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("VIBESENSOR_WS_DEBUG", "definitely")

    with pytest.raises(ValidationError, match="ws_debug"):
        WebSocketEnvSettings()


def test_update_env_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_backend_env(monkeypatch)

    settings = UpdateEnvSettings()

    assert settings.repo_path == DEFAULT_UPDATE_REPO_PATH
    assert settings.rollback_dir == DEFAULT_UPDATE_ROLLBACK_DIR
    assert settings.update_state_path == DEFAULT_UPDATE_STATE_PATH
    assert settings.update_sudo_wrapper is None
    assert settings.firmware_cache_dir == DEFAULT_FIRMWARE_CACHE_DIR
    assert settings.firmware_repo == "Skamba/VibeSensor"
    assert settings.firmware_channel == "stable"
    assert settings.firmware_pinned_tag == ""
    assert settings.server_repo == "Skamba/VibeSensor"
    assert settings.github_token == ""


def test_update_env_settings_accept_env_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("VIBESENSOR_REPO_PATH", str(tmp_path / "repo"))
    monkeypatch.setenv("VIBESENSOR_ROLLBACK_DIR", str(tmp_path / "rollback"))
    monkeypatch.setenv("VIBESENSOR_UPDATE_STATE_PATH", str(tmp_path / "update-status.json"))
    monkeypatch.setenv("VIBESENSOR_UPDATE_SUDO_WRAPPER", str(tmp_path / "sudo-wrapper.sh"))
    monkeypatch.setenv("VIBESENSOR_FIRMWARE_CACHE_DIR", str(tmp_path / "firmware"))
    monkeypatch.setenv("VIBESENSOR_FIRMWARE_REPO", "example/fw")
    monkeypatch.setenv("VIBESENSOR_FIRMWARE_CHANNEL", "prerelease")
    monkeypatch.setenv("VIBESENSOR_FIRMWARE_PINNED_TAG", "fw-v1.2.3")
    monkeypatch.setenv("VIBESENSOR_SERVER_REPO", "example/server")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")

    settings = UpdateEnvSettings()

    assert settings.repo_path == tmp_path / "repo"
    assert settings.rollback_dir == tmp_path / "rollback"
    assert settings.update_state_path == tmp_path / "update-status.json"
    assert settings.update_sudo_wrapper == tmp_path / "sudo-wrapper.sh"
    assert settings.firmware_cache_dir == tmp_path / "firmware"
    assert settings.firmware_repo == "example/fw"
    assert settings.firmware_channel == "prerelease"
    assert settings.firmware_pinned_tag == "fw-v1.2.3"
    assert settings.server_repo == "example/server"
    assert settings.github_token == "ghp_test123"


def test_update_env_settings_ignore_empty_env_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("VIBESENSOR_REPO_PATH", "")
    monkeypatch.setenv("VIBESENSOR_FIRMWARE_REPO", "")
    monkeypatch.setenv("VIBESENSOR_SERVER_REPO", "")
    monkeypatch.setenv("GITHUB_TOKEN", "")

    settings = UpdateEnvSettings()

    assert settings.repo_path == DEFAULT_UPDATE_REPO_PATH
    assert settings.firmware_repo == "Skamba/VibeSensor"
    assert settings.server_repo == "Skamba/VibeSensor"
    assert settings.github_token == ""


def test_update_env_settings_reject_invalid_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("VIBESENSOR_FIRMWARE_CHANNEL", "beta")

    with pytest.raises(ValidationError, match="firmware_channel"):
        UpdateEnvSettings()


def test_process_settings_summary_redacts_github_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_backend_env(monkeypatch)
    monkeypatch.setenv("VIBESENSOR_REPO_PATH", str(tmp_path / "repo"))
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")

    summary = summarize_process_settings()

    assert summary["repo_path"] == str(tmp_path / "repo")
    assert summary["github_token_configured"] is True
    assert "ghp_secret" not in str(summary)
