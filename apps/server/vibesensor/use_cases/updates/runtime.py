"""Runtime composition for the updater's public facade."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from vibesensor.use_cases.updates.cleanup import UpdateCleanupCoordinator
from vibesensor.use_cases.updates.completion import UpdateCompletionCoordinator
from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.installer import UpdateInstaller, UpdateInstallerConfig
from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdateValidationConfig,
)
from vibesensor.use_cases.updates.preparation import UpdatePreparationCoordinator
from vibesensor.use_cases.updates.release_deployment import UpdateReleaseDeployer
from vibesensor.use_cases.updates.release_installation import (
    UpdateReleaseInstallationCoordinator,
)
from vibesensor.use_cases.updates.release_planner import UpdateReleasePlanner
from vibesensor.use_cases.updates.release_resolution import ServerReleaseResolver
from vibesensor.use_cases.updates.release_staging import ServerReleaseStager
from vibesensor.use_cases.updates.restart_scheduler import UpdateRestartScheduler
from vibesensor.use_cases.updates.runner import CommandRunner, UpdateCommandExecutor
from vibesensor.use_cases.updates.startup_recovery import UpdateStartupRecoveryCoordinator
from vibesensor.use_cases.updates.status import (
    UpdateStateStore,
    UpdateStatusController,
    UpdateStatusRecorder,
    UpdateStatusServices,
    build_update_status_services,
    collect_runtime_details,
)
from vibesensor.use_cases.updates.transport_coordinator import UpdateTransportCoordinator
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
    status_services: UpdateStatusServices
    workflow_runner: UpdateWorkflowRunner
    usb_status_service: UsbInternetStatusReader
    startup_recovery: UpdateStartupRecoveryCoordinator
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
    status_services = _build_status_services(
        repo=config.repo,
        state_store=active_state_store,
    )
    commands = _build_command_executor(
        runner=active_runner,
        recorder=status_services.recorder,
    )
    status_service = usb_internet_service or UsbInternetStatusService(runner=active_runner)
    transport_sessions = _build_transport_sessions(
        commands=commands,
        status_controller=status_services.controller,
        recorder=status_services.recorder,
        wifi_config=config.wifi_config,
        status_service=status_service,
    )
    transport_coordinator = UpdateTransportCoordinator(sessions=transport_sessions)
    workflow = _build_update_workflow(
        commands=commands,
        status_controller=status_services.controller,
        recorder=status_services.recorder,
        config=config,
        transport_coordinator=transport_coordinator,
    )
    return UpdateManagerRuntime(
        status_services=status_services,
        workflow_runner=UpdateWorkflowRunner(
            status_controller=status_services.controller,
            status_recorder=status_services.recorder,
            cleanup=UpdateCleanupCoordinator(
                status_controller=status_services.controller,
                status_recorder=status_services.recorder,
                transport_coordinator=transport_coordinator,
                repo=config.repo,
                logger=LOGGER,
            ),
            timeout_s=UPDATE_TIMEOUT_S,
        ),
        usb_status_service=status_service,
        startup_recovery=UpdateStartupRecoveryCoordinator(
            status_session=status_services.session,
            status_controller=status_services.controller,
            status_recorder=status_services.recorder,
            transport_coordinator=transport_coordinator,
        ),
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


def _build_status_services(
    *,
    repo: Path,
    state_store: UpdateStateStore,
) -> UpdateStatusServices:
    loaded = state_store.load()
    status_services = build_update_status_services(
        state_store=state_store,
        status=loaded if loaded is not None else UpdateJobStatus(),
    )
    status_services.recorder.set_runtime(collect_runtime_details(repo))
    return status_services


def _build_command_executor(
    *,
    runner: CommandRunner,
    recorder: UpdateStatusRecorder,
) -> UpdateCommandExecutor:
    return UpdateCommandExecutor(runner=runner, recorder=recorder)


def _build_transport_sessions(
    *,
    commands: UpdateCommandExecutor,
    status_controller: UpdateStatusController,
    recorder: UpdateStatusRecorder,
    wifi_config: UpdateWifiConfig,
    status_service: UsbInternetStatusReader,
) -> UpdateTransportSessions:
    return UpdateTransportSessions(
        wifi=UpdateWifiSession(
            commands=commands,
            status_controller=status_controller,
            status_recorder=recorder,
            config=wifi_config,
        ),
        usb_internet=UpdateUsbInternetSession(
            status_service=status_service,
            commands=commands,
            status_controller=status_controller,
            status_recorder=recorder,
            config=wifi_config,
        ),
    )


def _build_release_components(
    *,
    commands: UpdateCommandExecutor,
    status_controller: UpdateStatusController,
    recorder: UpdateStatusRecorder,
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
        status_recorder=recorder,
        repo=config.repo,
        timeout_s=ESP_FIRMWARE_REFRESH_TIMEOUT_S,
    )
    installer = UpdateInstaller(
        commands=commands,
        status_controller=status_controller,
        status_recorder=recorder,
        config=config.installer_config,
    )
    installation = UpdateReleaseInstallationCoordinator(
        installer=installer,
        status_controller=status_controller,
        status_recorder=recorder,
    )
    return (
        ServerReleaseResolver(
            status_controller=status_controller,
            status_recorder=recorder,
            rollback_dir=config.rollback_dir,
        ),
        ServerReleaseStager(
            status_controller=status_controller,
            status_recorder=recorder,
            rollback_dir=config.rollback_dir,
        ),
        UpdateReleaseDeployer(
            installation=installation,
            firmware_refresher=firmware_refresher,
        ),
        firmware_refresher,
        UpdateRestartScheduler(
            commands=commands,
            status_recorder=recorder,
            service_name=UPDATE_SERVICE_NAME,
            restart_unit=UPDATE_RESTART_UNIT,
        ),
    )


def _build_update_workflow(
    *,
    commands: UpdateCommandExecutor,
    status_controller: UpdateStatusController,
    recorder: UpdateStatusRecorder,
    config: UpdateRuntimeConfig,
    transport_coordinator: UpdateTransportCoordinator,
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
        status_controller=status_controller,
        recorder=recorder,
        config=config,
    )
    return UpdateWorkflow(
        preparation=UpdatePreparationCoordinator(
            status_controller=status_controller,
            status_recorder=recorder,
            commands=commands,
            transport_coordinator=transport_coordinator,
            validation_config=config.validation_config,
            current_version_provider=current_version_provider,
        ),
        release_planner=UpdateReleasePlanner(
            status_controller=status_controller,
            status_recorder=recorder,
            resolver=resolver,
        ),
        workflow_executor=UpdateWorkflowExecutor(
            stager=stager,
            deployer=deployer,
            firmware_refresher=firmware_refresher,
            completion=UpdateCompletionCoordinator(
                transport_coordinator=transport_coordinator,
                status_recorder=recorder,
                restart_scheduler=restart_scheduler,
            ),
        ),
    )
