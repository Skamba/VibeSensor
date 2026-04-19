"""Updater runtime configuration resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vibesensor.app.process_settings import (
    DEFAULT_UPDATE_ROLLBACK_DIR,
    load_update_env_settings,
)
from vibesensor.use_cases.updates.installer import UpdateInstallerConfig
from vibesensor.use_cases.updates.models import UpdateValidationConfig
from vibesensor.use_cases.updates.releases.models import (
    ReleaseFetcherConfig,
    resolve_release_fetcher_config,
)
from vibesensor.use_cases.updates.validation import MIN_FREE_DISK_BYTES
from vibesensor.use_cases.updates.wifi.wifi_config import (
    UpdateWifiConfig,
    build_default_wifi_config,
)

__all__ = ["UpdateRuntimeConfig", "resolve_update_runtime_config"]

REINSTALL_OP_TIMEOUT_S = 180
DEFAULT_ROLLBACK_DIR = str(DEFAULT_UPDATE_ROLLBACK_DIR)
ESP_FIRMWARE_REFRESH_TIMEOUT_S = 240
UPDATE_RESTART_UNIT = "vibesensor-post-update-restart"
UPDATE_SERVICE_NAME = "vibesensor.service"


@dataclass(frozen=True, slots=True)
class UpdateExecutionConfig:
    firmware_refresh_timeout_s: float
    restart_unit: str
    service_name: str


@dataclass(frozen=True, slots=True)
class UpdateRuntimeConfig:
    repo: Path
    rollback_dir: Path
    wifi_config: UpdateWifiConfig
    installer_config: UpdateInstallerConfig
    validation_config: UpdateValidationConfig
    release_fetcher_config: ReleaseFetcherConfig
    execution_config: UpdateExecutionConfig


def resolve_update_runtime_config(
    *,
    repo_path: str | None,
    rollback_dir: str | None,
    ap_con_name: str,
    wifi_ifname: str,
) -> UpdateRuntimeConfig:
    env_settings = load_update_env_settings()
    repo = Path(repo_path).expanduser() if repo_path else env_settings.repo_path
    resolved_rollback_dir = (
        Path(rollback_dir).expanduser() if rollback_dir else env_settings.rollback_dir
    )
    wifi_config = build_default_wifi_config(
        ap_con_name=ap_con_name,
        wifi_ifname=wifi_ifname,
    )
    return UpdateRuntimeConfig(
        repo=repo,
        rollback_dir=resolved_rollback_dir,
        wifi_config=wifi_config,
        installer_config=UpdateInstallerConfig(
            repo=repo,
            rollback_dir=resolved_rollback_dir,
            reinstall_timeout_s=REINSTALL_OP_TIMEOUT_S,
        ),
        validation_config=UpdateValidationConfig(
            rollback_dir=resolved_rollback_dir,
            min_free_disk_bytes=MIN_FREE_DISK_BYTES,
        ),
        release_fetcher_config=resolve_release_fetcher_config(),
        execution_config=UpdateExecutionConfig(
            firmware_refresh_timeout_s=ESP_FIRMWARE_REFRESH_TIMEOUT_S,
            restart_unit=UPDATE_RESTART_UNIT,
            service_name=UPDATE_SERVICE_NAME,
        ),
    )
