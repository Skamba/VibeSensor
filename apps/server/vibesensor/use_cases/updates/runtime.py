"""Runtime composition for the canonical updater manager."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.installer import UpdateInstaller, UpdateInstallerConfig
from vibesensor.use_cases.updates.manager import UpdateManager
from vibesensor.use_cases.updates.models import (
    UpdateValidationConfig,
)
from vibesensor.use_cases.updates.preparation import UpdatePreparationCoordinator
from vibesensor.use_cases.updates.release_deployment import (
    UpdateReleaseDeploymentCoordinator,
)
from vibesensor.use_cases.updates.release_planner import UpdateReleasePlanner
from vibesensor.use_cases.updates.release_resolution import ServerReleaseResolver
from vibesensor.use_cases.updates.release_staging import ServerReleaseStager
from vibesensor.use_cases.updates.restart_scheduler import UpdateRestartScheduler
from vibesensor.use_cases.updates.runner import (
    CommandRunner,
    UpdateCommandExecutor,
    UpdateStatusCommandReporter,
)
from vibesensor.use_cases.updates.runtime_refresh import UpdateRuntimeDetailsRefresher
from vibesensor.use_cases.updates.startup_recovery import UpdateStartupRecoveryCoordinator
from vibesensor.use_cases.updates.status import (
    UpdateStateStore,
    UpdateStatusTracker,
    build_update_status_tracker,
    collect_runtime_details,
)
from vibesensor.use_cases.updates.transport_coordinator import UpdateTransportCoordinator
from vibesensor.use_cases.updates.transport_lifecycles import UpdateTransportLifecycles
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

LOGGER = logging.getLogger(__name__)

UPDATE_TIMEOUT_S = 600
REINSTALL_OP_TIMEOUT_S = 180
ESP_FIRMWARE_REFRESH_TIMEOUT_S = 240
DEFAULT_ROLLBACK_DIR = "/var/lib/vibesensor/rollback"
UPDATE_RESTART_UNIT = "vibesensor-post-update-restart"
UPDATE_SERVICE_NAME = "vibesensor.service"


@dataclass(frozen=True, slots=True)
class UpdateRuntimeConfig:
    repo: Path
    rollback_dir: Path
    wifi_config: UpdateWifiConfig
    installer_config: UpdateInstallerConfig
    validation_config: UpdateValidationConfig


def build_update_manager(
    *,
    runner: CommandRunner | None = None,
    repo_path: str | None = None,
    ap_con_name: str = "VibeSensor-AP",
    wifi_ifname: str = "wlan0",
    rollback_dir: str | None = None,
    state_store: UpdateStateStore | None = None,
    usb_internet_service: UsbInternetStatusReader | None = None,
) -> UpdateManager:
    active_runner = runner or CommandRunner()
    config = _resolve_runtime_config(
        repo_path=repo_path,
        rollback_dir=rollback_dir,
        ap_con_name=ap_con_name,
        wifi_ifname=wifi_ifname,
    )
    active_state_store = state_store or UpdateStateStore()
    status = _build_status_tracker(
        repo=config.repo,
        state_store=active_state_store,
    )
    commands = _build_command_executor(
        runner=active_runner,
        status=status,
    )
    status_service = usb_internet_service or UsbInternetStatusService(runner=active_runner)
    transport_lifecycles = _build_transport_lifecycles(
        commands=commands,
        status=status,
        wifi_config=config.wifi_config,
        status_service=status_service,
    )
    transport_coordinator = UpdateTransportCoordinator(
        lifecycles=transport_lifecycles,
        status=status,
        logger=LOGGER,
    )
    workflow = _build_update_workflow(
        commands=commands,
        status=status,
        config=config,
        transport_coordinator=transport_coordinator,
    )
    return UpdateManager(
        status=status,
        usb_status_service=status_service,
        startup_recovery=UpdateStartupRecoveryCoordinator(
            status=status,
            transport_coordinator=transport_coordinator,
        ),
        workflow=workflow,
        timeout_s=UPDATE_TIMEOUT_S,
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
    status = build_update_status_tracker(
        state_store=state_store,
        status=loaded,
    )
    status.set_runtime(collect_runtime_details(repo))
    return status


def _build_command_executor(
    *,
    runner: CommandRunner,
    status: UpdateStatusTracker,
) -> UpdateCommandExecutor:
    return UpdateCommandExecutor(
        runner=runner,
        reporter=UpdateStatusCommandReporter(status=status),
    )


def _build_transport_lifecycles(
    *,
    commands: UpdateCommandExecutor,
    status: UpdateStatusTracker,
    wifi_config: UpdateWifiConfig,
    status_service: UsbInternetStatusReader,
) -> UpdateTransportLifecycles:
    return UpdateTransportLifecycles(
        wifi=UpdateWifiSession(
            commands=commands,
            status=status,
            config=wifi_config,
        ),
        usb_internet=UpdateUsbInternetSession(
            status_service=status_service,
            commands=commands,
            status=status,
            config=wifi_config,
        ),
    )


def _build_release_components(
    *,
    commands: UpdateCommandExecutor,
    status: UpdateStatusTracker,
    config: UpdateRuntimeConfig,
) -> tuple[
    ServerReleaseResolver,
    ServerReleaseStager,
    UpdateReleaseDeploymentCoordinator,
    FirmwareRefresher,
    UpdateRestartScheduler,
]:
    firmware_refresher = FirmwareRefresher(
        commands=commands,
        status=status,
        repo=config.repo,
        timeout_s=ESP_FIRMWARE_REFRESH_TIMEOUT_S,
    )
    installer = UpdateInstaller(
        commands=commands,
        status=status,
        config=config.installer_config,
    )
    return (
        ServerReleaseResolver(
            status=status,
            rollback_dir=config.rollback_dir,
        ),
        ServerReleaseStager(
            status=status,
            rollback_dir=config.rollback_dir,
        ),
        UpdateReleaseDeploymentCoordinator(
            installer=installer,
            firmware_refresher=firmware_refresher,
            status=status,
        ),
        firmware_refresher,
        UpdateRestartScheduler(
            commands=commands,
            status=status,
            service_name=UPDATE_SERVICE_NAME,
            restart_unit=UPDATE_RESTART_UNIT,
        ),
    )


def _build_update_workflow(
    *,
    commands: UpdateCommandExecutor,
    status: UpdateStatusTracker,
    config: UpdateRuntimeConfig,
    transport_coordinator: UpdateTransportCoordinator,
) -> UpdateWorkflow:
    def current_version_provider() -> str:
        from vibesensor import __version__ as current_version

        return current_version

    (
        resolver,
        stager,
        deployment,
        firmware_refresher,
        restart_scheduler,
    ) = _build_release_components(
        commands=commands,
        status=status,
        config=config,
    )
    return UpdateWorkflow(
        preparation=UpdatePreparationCoordinator(
            status=status,
            commands=commands,
            transport_coordinator=transport_coordinator,
            validation_config=config.validation_config,
            current_version_provider=current_version_provider,
        ),
        release_planner=UpdateReleasePlanner(
            status=status,
            resolver=resolver,
        ),
        workflow_executor=UpdateWorkflowExecutor(
            stager=stager,
            deployment=deployment,
            firmware_refresher=firmware_refresher,
            restart_scheduler=restart_scheduler,
            status=status,
        ),
        transport_coordinator=transport_coordinator,
        runtime_details_refresher=UpdateRuntimeDetailsRefresher(
            status=status,
            repo=config.repo,
            logger=LOGGER,
        ),
    )
