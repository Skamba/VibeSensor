"""Public updater facade over focused update subsystems."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.installer import UpdateInstaller, UpdateInstallerConfig
from vibesensor.use_cases.updates.job_executor import UpdateJobExecutor
from vibesensor.use_cases.updates.job_lifecycle import UpdateJobLifecycleHandler
from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdateRequest,
    UpdateTransport,
    UpdateValidationConfig,
    UsbInternetStatus,
    validate_update_request,
)
from vibesensor.use_cases.updates.recovery import InterruptedUpdateRecovery
from vibesensor.use_cases.updates.release_coordinator import UpdateReleaseCoordinator
from vibesensor.use_cases.updates.release_deployment import UpdateReleaseDeployer
from vibesensor.use_cases.updates.release_resolution import ServerReleaseResolver
from vibesensor.use_cases.updates.release_staging import ServerReleaseStager
from vibesensor.use_cases.updates.restart_scheduler import UpdateRestartScheduler
from vibesensor.use_cases.updates.runner import CommandRunner, UpdateCommandExecutor
from vibesensor.use_cases.updates.status import (
    UpdateStateStore,
    UpdateStatusTracker,
    collect_runtime_details,
)
from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSessions
from vibesensor.use_cases.updates.usb_internet import (
    UpdateUsbInternetOrchestrator,
    UsbInternetStatusService,
)
from vibesensor.use_cases.updates.validation import (
    MIN_FREE_DISK_BYTES,
)
from vibesensor.use_cases.updates.wifi import (
    UpdateWifiOrchestrator,
    build_default_wifi_config,
)
from vibesensor.use_cases.updates.workflow import UpdateWorkflow

LOGGER = logging.getLogger(__name__)

UPDATE_TIMEOUT_S = 600
REINSTALL_OP_TIMEOUT_S = 180
ESP_FIRMWARE_REFRESH_TIMEOUT_S = 240
DEFAULT_ROLLBACK_DIR = "/var/lib/vibesensor/rollback"
UPDATE_RESTART_UNIT = "vibesensor-post-update-restart"
UPDATE_SERVICE_NAME = "vibesensor.service"


class UpdateManager:
    """Public update API used by routes and runtime lifecycle."""

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        repo_path: str | None = None,
        ap_con_name: str = "VibeSensor-AP",
        wifi_ifname: str = "wlan0",
        rollback_dir: str | None = None,
        state_store: UpdateStateStore | None = None,
        usb_internet_service: UsbInternetStatusService | None = None,
    ) -> None:
        self._runner = runner or CommandRunner()
        self._repo_path = repo_path or os.environ.get("VIBESENSOR_REPO_PATH", "/opt/VibeSensor")
        self._repo = Path(self._repo_path)
        self._wifi_config = build_default_wifi_config(
            ap_con_name=ap_con_name,
            wifi_ifname=wifi_ifname,
        )
        self._rollback_dir = Path(
            rollback_dir or os.environ.get("VIBESENSOR_ROLLBACK_DIR", DEFAULT_ROLLBACK_DIR),
        )
        self._state_store = state_store or UpdateStateStore()
        loaded = self._state_store.load()
        self._tracker = UpdateStatusTracker(
            state_store=self._state_store,
            status=loaded if loaded is not None else UpdateJobStatus(),
        )
        self._tracker.set_runtime(collect_runtime_details(self._repo))
        self._executor = UpdateJobExecutor(task_name="system-update")
        self._usb_internet_service = usb_internet_service or UsbInternetStatusService(
            runner=self._runner
        )

        self._lifecycle = UpdateJobLifecycleHandler(
            tracker=self._tracker,
            repo=self._repo,
            transport_sessions_factory=lambda: self._build_transport_sessions(),
            logger=LOGGER,
        )
        self._recovery = InterruptedUpdateRecovery(
            tracker=self._tracker,
            transport_sessions_factory=lambda: self._build_transport_sessions(),
        )

        # Build config objects once — shared by workflow, snapshot, and rollback.
        self._installer_config = UpdateInstallerConfig(
            repo=self._repo,
            rollback_dir=self._rollback_dir,
            reinstall_timeout_s=REINSTALL_OP_TIMEOUT_S,
        )
        self._validation_config = UpdateValidationConfig(
            rollback_dir=self._rollback_dir,
            min_free_disk_bytes=MIN_FREE_DISK_BYTES,
        )

    @property
    def status(self) -> UpdateJobStatus:
        return self._tracker.status

    @property
    def job_task(self) -> asyncio.Task[None] | None:
        return self._executor.job_task

    async def get_usb_internet_status(self) -> UsbInternetStatus:
        if isinstance(self._usb_internet_service, UsbInternetStatusService):
            return await self._usb_internet_service.snapshot(activate=True)
        return await self._usb_internet_service.snapshot()

    def start(
        self,
        ssid: str | None = None,
        password: str = "",
        *,
        transport: UpdateTransport = UpdateTransport.wifi,
    ) -> None:
        request = validate_update_request(ssid, password, transport=transport)
        self._executor.start(
            lambda: self._run_update(request),
            before_start=lambda: self._lifecycle.prepare_start(request),
        )

    def cancel(self) -> bool:
        return self._executor.cancel()

    async def startup_recover(self) -> None:
        if self._recovery.needs_recovery():
            await self._recovery.recover()

    async def _run_update(
        self,
        request_or_ssid: UpdateRequest | str,
        password: str | None = None,
    ) -> None:
        await self._executor.run(
            workflow_factory=lambda: self._run_update_inner(request_or_ssid, password),
            timeout_s=UPDATE_TIMEOUT_S,
            on_timeout=lambda: self._lifecycle.handle_timeout(UPDATE_TIMEOUT_S),
            on_cancelled=self._lifecycle.handle_cancelled,
            on_unexpected=self._lifecycle.handle_unexpected,
            cleanup=self._lifecycle.cleanup_after_update,
            on_cancelled_cleanup_error=self._lifecycle.handle_cancelled_cleanup_error,
        )

    async def _run_update_inner(
        self,
        request_or_ssid: UpdateRequest | str,
        password: str | None = None,
    ) -> None:
        request = (
            request_or_ssid
            if isinstance(request_or_ssid, UpdateRequest)
            else UpdateRequest(
                transport=UpdateTransport.wifi,
                ssid=request_or_ssid,
                password=password or "",
            )
        )
        workflow = self._build_workflow()
        await workflow.execute(request)

    def _build_workflow(self) -> UpdateWorkflow:
        commands = self._build_command_executor()
        return UpdateWorkflow(
            tracker=self._tracker,
            commands=commands,
            transport_sessions=self._build_transport_sessions(commands=commands),
            release_coordinator=self._build_release_coordinator(commands),
            cancel_requested=self._executor.cancel_requested,
            validation_config=self._validation_config,
        )

    def _build_command_executor(self) -> UpdateCommandExecutor:
        return UpdateCommandExecutor(runner=self._runner, tracker=self._tracker)

    def _build_transport_sessions(
        self,
        *,
        commands: UpdateCommandExecutor | None = None,
    ) -> UpdateTransportSessions:
        active_commands = commands or self._build_command_executor()
        return UpdateTransportSessions(
            wifi=UpdateWifiOrchestrator(
                commands=active_commands,
                tracker=self._tracker,
                config=self._wifi_config,
            ),
            usb_internet=UpdateUsbInternetOrchestrator(
                status_service=self._usb_internet_service,
                commands=active_commands,
                tracker=self._tracker,
                config=self._wifi_config,
            ),
        )

    def _build_firmware_refresher(
        self,
        commands: UpdateCommandExecutor,
    ) -> FirmwareRefresher:
        return FirmwareRefresher(
            commands=commands,
            tracker=self._tracker,
            repo=self._repo,
            timeout_s=ESP_FIRMWARE_REFRESH_TIMEOUT_S,
        )

    def _build_release_coordinator(
        self,
        commands: UpdateCommandExecutor,
    ) -> UpdateReleaseCoordinator:
        firmware_refresher = self._build_firmware_refresher(commands)
        installer = UpdateInstaller(
            commands=commands,
            tracker=self._tracker,
            config=self._installer_config,
        )
        return UpdateReleaseCoordinator(
            tracker=self._tracker,
            resolver=ServerReleaseResolver(
                tracker=self._tracker,
                rollback_dir=self._rollback_dir,
            ),
            stager=ServerReleaseStager(
                tracker=self._tracker,
                rollback_dir=self._rollback_dir,
            ),
            deployer=UpdateReleaseDeployer(
                tracker=self._tracker,
                installer=installer,
                firmware_refresher=firmware_refresher,
                cancel_requested=self._executor.cancel_requested,
            ),
            firmware_refresher=firmware_refresher,
            restart_scheduler=UpdateRestartScheduler(
                commands=commands,
                tracker=self._tracker,
                service_name=UPDATE_SERVICE_NAME,
                restart_unit=UPDATE_RESTART_UNIT,
            ),
            cancel_requested=self._executor.cancel_requested,
        )
