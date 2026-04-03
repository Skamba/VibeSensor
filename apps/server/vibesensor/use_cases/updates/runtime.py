"""Runtime composition for the updater's public facade."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from vibesensor.use_cases.updates.cleanup import UpdateCleanupCoordinator
from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.installer import UpdateInstaller, UpdateInstallerConfig
from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdateValidationConfig,
)
from vibesensor.use_cases.updates.preparation import UpdatePreparationCoordinator
from vibesensor.use_cases.updates.release_deployment import UpdateReleaseDeployer
from vibesensor.use_cases.updates.release_planner import UpdateReleasePlanner
from vibesensor.use_cases.updates.release_resolution import ServerReleaseResolver
from vibesensor.use_cases.updates.release_staging import ServerReleaseStager
from vibesensor.use_cases.updates.restart_scheduler import UpdateRestartScheduler
from vibesensor.use_cases.updates.runner import CommandRunner, UpdateCommandExecutor
from vibesensor.use_cases.updates.status import (
    UpdateStateStore,
    UpdateStatusTracker,
    collect_runtime_details,
)
from vibesensor.use_cases.updates.success_finalizer import UpdateSuccessFinalizer
from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSessions
from vibesensor.use_cases.updates.usb_status import (
    UsbInternetStatusReader,
    UsbInternetStatusService,
)
from vibesensor.use_cases.updates.usb_transport import UpdateUsbInternetSession
from vibesensor.use_cases.updates.validation import MIN_FREE_DISK_BYTES
from vibesensor.use_cases.updates.wifi import UpdateWifiSession, build_default_wifi_config
from vibesensor.use_cases.updates.wifi.wifi_config import UpdateWifiConfig
from vibesensor.use_cases.updates.workflow import UpdateWorkflow
from vibesensor.use_cases.updates.workflow_executor import UpdateWorkflowExecutor
from vibesensor.use_cases.updates.workflow_runner import UpdateWorkflowRunner

LOGGER = logging.getLogger(__name__)

UPDATE_TIMEOUT_S = 600
REINSTALL_OP_TIMEOUT_S = 180
ESP_FIRMWARE_REFRESH_TIMEOUT_S = 240
DEFAULT_ROLLBACK_DIR = "/var/lib/vibesensor/rollback"
UPDATE_RESTART_UNIT = "vibesensor-post-update-restart"
UPDATE_SERVICE_NAME = "vibesensor.service"


@dataclass(frozen=True, slots=True)
class UpdateManagerRuntime:
    tracker: UpdateStatusTracker
    workflow_runner: UpdateWorkflowRunner
    usb_status_service: UsbInternetStatusReader
    transport_sessions: UpdateTransportSessions
    workflow: UpdateWorkflow


@dataclass(frozen=True, slots=True)
class UpdateRuntimeConfig:
    repo: Path
    rollback_dir: Path
    wifi_config: UpdateWifiConfig
    installer_config: UpdateInstallerConfig
    validation_config: UpdateValidationConfig


def build_update_manager_runtime(
    *,
    runner: CommandRunner | None = None,
    repo_path: str | None = None,
    ap_con_name: str = "VibeSensor-AP",
    wifi_ifname: str = "wlan0",
    rollback_dir: str | None = None,
    state_store: UpdateStateStore | None = None,
    usb_internet_service: UsbInternetStatusReader | None = None,
) -> UpdateManagerRuntime:
    active_runner = runner or CommandRunner()
    config = _resolve_runtime_config(
        repo_path=repo_path,
        rollback_dir=rollback_dir,
        ap_con_name=ap_con_name,
        wifi_ifname=wifi_ifname,
    )
    active_state_store = state_store or UpdateStateStore()
    tracker = _build_status_tracker(
        repo=config.repo,
        state_store=active_state_store,
    )
    commands = _build_command_executor(
        runner=active_runner,
        tracker=tracker,
    )
    status_service = usb_internet_service or UsbInternetStatusService(runner=active_runner)
    transport_sessions = _build_transport_sessions(
        commands=commands,
        tracker=tracker,
        wifi_config=config.wifi_config,
        status_service=status_service,
    )
    workflow = _build_update_workflow(
        commands=commands,
        tracker=tracker,
        config=config,
        transport_sessions=transport_sessions,
    )
    return UpdateManagerRuntime(
        tracker=tracker,
        workflow_runner=UpdateWorkflowRunner(
            tracker=tracker,
            cleanup=UpdateCleanupCoordinator(
                tracker=tracker,
                repo=config.repo,
                logger=LOGGER,
            ),
            timeout_s=UPDATE_TIMEOUT_S,
        ),
        usb_status_service=status_service,
        transport_sessions=transport_sessions,
        workflow=workflow,
    )


def _resolve_runtime_config(
    *,
    repo_path: str | None,
    rollback_dir: str | None,
    ap_con_name: str,
    wifi_ifname: str,
) -> UpdateRuntimeConfig:
    repo = Path(repo_path or os.environ.get("VIBESENSOR_REPO_PATH", "/opt/VibeSensor"))
    resolved_rollback_dir = Path(
        rollback_dir or os.environ.get("VIBESENSOR_ROLLBACK_DIR", DEFAULT_ROLLBACK_DIR),
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
    )


def _build_status_tracker(
    *,
    repo: Path,
    state_store: UpdateStateStore,
) -> UpdateStatusTracker:
    loaded = state_store.load()
    tracker = UpdateStatusTracker(
        state_store=state_store,
        status=loaded if loaded is not None else UpdateJobStatus(),
    )
    tracker.set_runtime(collect_runtime_details(repo))
    return tracker


def _build_command_executor(
    *,
    runner: CommandRunner,
    tracker: UpdateStatusTracker,
) -> UpdateCommandExecutor:
    return UpdateCommandExecutor(runner=runner, tracker=tracker)


def _build_transport_sessions(
    *,
    commands: UpdateCommandExecutor,
    tracker: UpdateStatusTracker,
    wifi_config: UpdateWifiConfig,
    status_service: UsbInternetStatusReader,
) -> UpdateTransportSessions:
    return UpdateTransportSessions(
        wifi=UpdateWifiSession(
            commands=commands,
            tracker=tracker,
            config=wifi_config,
        ),
        usb_internet=UpdateUsbInternetSession(
            status_service=status_service,
            commands=commands,
            tracker=tracker,
            config=wifi_config,
        ),
    )


def _build_release_components(
    *,
    commands: UpdateCommandExecutor,
    tracker: UpdateStatusTracker,
    config: UpdateRuntimeConfig,
) -> tuple[
    ServerReleaseResolver,
    ServerReleaseStager,
    UpdateReleaseDeployer,
    FirmwareRefresher,
    UpdateRestartScheduler,
]:
    firmware_refresher = FirmwareRefresher(
        commands=commands,
        tracker=tracker,
        repo=config.repo,
        timeout_s=ESP_FIRMWARE_REFRESH_TIMEOUT_S,
    )
    installer = UpdateInstaller(
        commands=commands,
        tracker=tracker,
        config=config.installer_config,
    )
    return (
        ServerReleaseResolver(
            tracker=tracker,
            rollback_dir=config.rollback_dir,
        ),
        ServerReleaseStager(
            tracker=tracker,
            rollback_dir=config.rollback_dir,
        ),
        UpdateReleaseDeployer(
            tracker=tracker,
            installer=installer,
            firmware_refresher=firmware_refresher,
        ),
        firmware_refresher,
        UpdateRestartScheduler(
            commands=commands,
            tracker=tracker,
            service_name=UPDATE_SERVICE_NAME,
            restart_unit=UPDATE_RESTART_UNIT,
        ),
    )


def _build_update_workflow(
    *,
    commands: UpdateCommandExecutor,
    tracker: UpdateStatusTracker,
    config: UpdateRuntimeConfig,
    transport_sessions: UpdateTransportSessions,
) -> UpdateWorkflow:
    def current_version_provider() -> str:
        from vibesensor import __version__ as current_version

        return current_version

    (
        resolver,
        stager,
        deployer,
        firmware_refresher,
        restart_scheduler,
    ) = _build_release_components(
        commands=commands,
        tracker=tracker,
        config=config,
    )
    return UpdateWorkflow(
        preparation=UpdatePreparationCoordinator(
            tracker=tracker,
            commands=commands,
            transport_sessions=transport_sessions,
            validation_config=config.validation_config,
            current_version_provider=current_version_provider,
        ),
        release_planner=UpdateReleasePlanner(
            tracker=tracker,
            resolver=resolver,
        ),
        workflow_executor=UpdateWorkflowExecutor(
            stager=stager,
            deployer=deployer,
            firmware_refresher=firmware_refresher,
            finalizer=UpdateSuccessFinalizer(
                tracker=tracker,
                restart_scheduler=restart_scheduler,
            ),
        ),
    )
