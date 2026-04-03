"""Runtime composition for the updater's public facade."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from vibesensor.use_cases.updates.coordinator import UpdateCoordinator
from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.installer import UpdateInstaller, UpdateInstallerConfig
from vibesensor.use_cases.updates.job_executor import UpdateJobExecutor
from vibesensor.use_cases.updates.job_lifecycle import UpdateJobLifecycleHandler
from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdateValidationConfig,
)
from vibesensor.use_cases.updates.preparation import UpdatePreparationCoordinator
from vibesensor.use_cases.updates.recovery import InterruptedUpdateRecovery
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
from vibesensor.use_cases.updates.transport_controller import UpdateTransportController
from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSessions
from vibesensor.use_cases.updates.usb_status import (
    UsbInternetStatusReader,
    UsbInternetStatusService,
)
from vibesensor.use_cases.updates.usb_transport import UpdateUsbInternetSession
from vibesensor.use_cases.updates.validation import MIN_FREE_DISK_BYTES
from vibesensor.use_cases.updates.wifi import UpdateWifiSession, build_default_wifi_config
from vibesensor.use_cases.updates.workflow_executor import UpdateWorkflowExecutor

LOGGER = logging.getLogger(__name__)

REINSTALL_OP_TIMEOUT_S = 180
ESP_FIRMWARE_REFRESH_TIMEOUT_S = 240
DEFAULT_ROLLBACK_DIR = "/var/lib/vibesensor/rollback"
UPDATE_RESTART_UNIT = "vibesensor-post-update-restart"
UPDATE_SERVICE_NAME = "vibesensor.service"


@dataclass(frozen=True, slots=True)
class UpdateManagerRuntime:
    tracker: UpdateStatusTracker
    executor: UpdateJobExecutor
    lifecycle: UpdateJobLifecycleHandler
    recovery: InterruptedUpdateRecovery
    usb_status_service: UsbInternetStatusReader
    coordinator_factory: Callable[[], UpdateCoordinator]


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
    repo = Path(repo_path or os.environ.get("VIBESENSOR_REPO_PATH", "/opt/VibeSensor"))
    wifi_config = build_default_wifi_config(
        ap_con_name=ap_con_name,
        wifi_ifname=wifi_ifname,
    )
    resolved_rollback_dir = Path(
        rollback_dir or os.environ.get("VIBESENSOR_ROLLBACK_DIR", DEFAULT_ROLLBACK_DIR),
    )
    active_state_store = state_store or UpdateStateStore()
    loaded = active_state_store.load()
    tracker = UpdateStatusTracker(
        state_store=active_state_store,
        status=loaded if loaded is not None else UpdateJobStatus(),
    )
    tracker.set_runtime(collect_runtime_details(repo))
    executor = UpdateJobExecutor(task_name="system-update")
    status_service = usb_internet_service or UsbInternetStatusService(
        runner=active_runner,
    )

    installer_config = UpdateInstallerConfig(
        repo=repo,
        rollback_dir=resolved_rollback_dir,
        reinstall_timeout_s=REINSTALL_OP_TIMEOUT_S,
    )
    validation_config = UpdateValidationConfig(
        rollback_dir=resolved_rollback_dir,
        min_free_disk_bytes=MIN_FREE_DISK_BYTES,
    )

    def build_command_executor() -> UpdateCommandExecutor:
        return UpdateCommandExecutor(runner=active_runner, tracker=tracker)

    def build_transport_sessions(
        *,
        commands: UpdateCommandExecutor | None = None,
    ) -> UpdateTransportSessions:
        active_commands = commands or build_command_executor()
        return UpdateTransportSessions(
            wifi=UpdateWifiSession(
                commands=active_commands,
                tracker=tracker,
                config=wifi_config,
            ),
            usb_internet=UpdateUsbInternetSession(
                status_service=status_service,
                commands=active_commands,
                tracker=tracker,
                config=wifi_config,
            ),
        )

    def build_release_components(
        commands: UpdateCommandExecutor,
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
            repo=repo,
            timeout_s=ESP_FIRMWARE_REFRESH_TIMEOUT_S,
        )
        installer = UpdateInstaller(
            commands=commands,
            tracker=tracker,
            config=installer_config,
        )
        return (
            ServerReleaseResolver(
                tracker=tracker,
                rollback_dir=resolved_rollback_dir,
            ),
            ServerReleaseStager(
                tracker=tracker,
                rollback_dir=resolved_rollback_dir,
            ),
            UpdateReleaseDeployer(
                tracker=tracker,
                installer=installer,
                firmware_refresher=firmware_refresher,
                cancel_requested=executor.cancel_requested,
            ),
            firmware_refresher,
            UpdateRestartScheduler(
                commands=commands,
                tracker=tracker,
                service_name=UPDATE_SERVICE_NAME,
                restart_unit=UPDATE_RESTART_UNIT,
            ),
        )

    def build_coordinator() -> UpdateCoordinator:
        commands = build_command_executor()
        transport_sessions = build_transport_sessions(commands=commands)
        (
            resolver,
            stager,
            deployer,
            firmware_refresher,
            restart_scheduler,
        ) = build_release_components(commands)

        def current_version_provider() -> str:
            from vibesensor import __version__ as current_version

            return current_version

        return UpdateCoordinator(
            preparation=UpdatePreparationCoordinator(
                tracker=tracker,
                commands=commands,
                transport_controller=UpdateTransportController(sessions=transport_sessions),
                validation_config=validation_config,
                current_version_provider=current_version_provider,
                cancel_requested=executor.cancel_requested,
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
                cancel_requested=executor.cancel_requested,
            ),
            cancel_requested=executor.cancel_requested,
        )

    lifecycle = UpdateJobLifecycleHandler(
        tracker=tracker,
        repo=repo,
        transport_sessions_factory=lambda: build_transport_sessions(),
        logger=LOGGER,
    )
    recovery = InterruptedUpdateRecovery(
        tracker=tracker,
        transport_sessions_factory=lambda: build_transport_sessions(),
    )
    return UpdateManagerRuntime(
        tracker=tracker,
        executor=executor,
        lifecycle=lifecycle,
        recovery=recovery,
        usb_status_service=status_service,
        coordinator_factory=build_coordinator,
    )
