"""Composition of the canonical updater manager and its update job."""

from __future__ import annotations

import logging
from pathlib import Path

from vibesensor.shared.process_settings import (
    load_bootstrap_env_settings,
    load_update_env_settings,
)
from vibesensor.use_cases.updates.artifact_validation import WheelArtifactValidator
from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.job import UpdateJob
from vibesensor.use_cases.updates.manager import UpdateManager
from vibesensor.use_cases.updates.models import UpdateValidationConfig
from vibesensor.use_cases.updates.release_staging import ServerReleaseStager
from vibesensor.use_cases.updates.releases.models import resolve_release_fetcher_config
from vibesensor.use_cases.updates.releases.release_fetcher import ServerReleaseFetcher
from vibesensor.use_cases.updates.rollback import UpdateRollback
from vibesensor.use_cases.updates.runner import (
    CommandRunner,
    UpdateCommandExecutor,
    UpdateStatusCommandReporter,
)
from vibesensor.use_cases.updates.status import (
    UpdateStateStore,
    UpdateStatusTracker,
    collect_runtime_details,
)
from vibesensor.use_cases.updates.transport.coordinator import UpdateTransportCoordinator
from vibesensor.use_cases.updates.transport.usb_internet import UpdateUsbInternetSession
from vibesensor.use_cases.updates.usb_status import UsbInternetStatusService
from vibesensor.use_cases.updates.validation import MIN_FREE_DISK_BYTES
from vibesensor.use_cases.updates.wheel_installation import WheelInstallExecutor
from vibesensor.use_cases.updates.wifi.wifi_config import build_default_wifi_config
from vibesensor.use_cases.updates.wifi.wifi_session import UpdateWifiSession

__all__ = ["UPDATE_TIMEOUT_S", "build_update_manager"]

LOGGER = logging.getLogger(__name__)

UPDATE_TIMEOUT_S = 600
REINSTALL_OP_TIMEOUT_S = 180
ESP_FIRMWARE_REFRESH_TIMEOUT_S = 240


def build_update_manager(
    *,
    runner: CommandRunner | None = None,
    repo_path: str | None = None,
    ap_con_name: str = "VibeSensor-AP",
    wifi_ifname: str = "wlan0",
    rollback_dir: str | None = None,
    state_store: UpdateStateStore | None = None,
    usb_internet_service: UsbInternetStatusService | None = None,
    server_release_fetcher: ServerReleaseFetcher | None = None,
) -> UpdateManager:
    active_runner = runner or CommandRunner()
    env_settings = load_update_env_settings()
    bootstrap_settings = load_bootstrap_env_settings()
    repo = Path(repo_path).expanduser() if repo_path else env_settings.repo_path
    resolved_rollback_dir = (
        Path(rollback_dir).expanduser() if rollback_dir else env_settings.rollback_dir
    )
    smoke_config_path = bootstrap_settings.config_path or (
        repo / "apps" / "server" / "config.pi.yaml"
    )
    wifi_config = build_default_wifi_config(
        ap_con_name=ap_con_name,
        wifi_ifname=wifi_ifname,
    )

    active_state_store = state_store or UpdateStateStore()
    status = UpdateStatusTracker(
        state_store=active_state_store,
        status=active_state_store.load(),
    )
    status.set_runtime(collect_runtime_details(repo))
    commands = UpdateCommandExecutor(
        runner=active_runner,
        reporter=UpdateStatusCommandReporter(status=status),
    )

    usb_status_service = usb_internet_service or UsbInternetStatusService(runner=active_runner)
    transport = UpdateTransportCoordinator(
        wifi=UpdateWifiSession(
            commands=commands,
            status=status,
            config=wifi_config,
        ),
        usb_internet=UpdateUsbInternetSession(
            status_service=usb_status_service,
            commands=commands,
            status=status,
            config=wifi_config,
        ),
        logger=LOGGER,
    )

    release_fetcher = server_release_fetcher or ServerReleaseFetcher(
        resolve_release_fetcher_config(),
    )
    wheel_validator = WheelArtifactValidator(status=status)
    wheel_installer = WheelInstallExecutor(
        commands=commands,
        status=status,
        repo=repo,
        reinstall_timeout_s=REINSTALL_OP_TIMEOUT_S,
        wheel_validator=wheel_validator,
    )
    job = UpdateJob(
        status=status,
        commands=commands,
        transport=transport,
        release_fetcher=release_fetcher,
        stager=ServerReleaseStager(status=status, release_fetcher=release_fetcher),
        firmware_refresher=FirmwareRefresher(
            commands=commands,
            status=status,
            repo=repo,
            timeout_s=ESP_FIRMWARE_REFRESH_TIMEOUT_S,
        ),
        wheel_installer=wheel_installer,
        rollback=UpdateRollback(
            commands=commands,
            status=status,
            repo=repo,
            rollback_dir=resolved_rollback_dir,
            config_path=smoke_config_path,
            wheel_validator=wheel_validator,
            wheel_install_executor=wheel_installer,
        ),
        validation_config=UpdateValidationConfig(
            rollback_dir=resolved_rollback_dir,
            min_free_disk_bytes=MIN_FREE_DISK_BYTES,
        ),
        repo=repo,
    )
    return UpdateManager(
        status=status,
        job=job,
        usb_status_service=usb_status_service,
        timeout_s=UPDATE_TIMEOUT_S,
    )
