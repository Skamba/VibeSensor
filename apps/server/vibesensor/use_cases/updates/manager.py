"""Public updater facade over focused update subsystems."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
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
from vibesensor.use_cases.updates.runner import CommandRunner, UpdateCommandExecutor
from vibesensor.use_cases.updates.status import (
    UpdateStateStore,
    UpdateStatusTracker,
    collect_runtime_details,
)
from vibesensor.use_cases.updates.usb_internet import (
    UpdateUsbInternetOrchestrator,
    UsbInternetStatusService,
)
from vibesensor.use_cases.updates.validation import (
    MIN_FREE_DISK_BYTES,
)
from vibesensor.use_cases.updates.wifi import (
    UpdateWifiConfig,
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

CommandExecutorFactory = Callable[
    [CommandRunner, UpdateStatusTracker],
    UpdateCommandExecutor,
]
WifiOrchestratorFactory = Callable[
    [UpdateCommandExecutor, UpdateStatusTracker, UpdateWifiConfig],
    UpdateWifiOrchestrator,
]
InstallerFactory = Callable[
    [UpdateCommandExecutor, UpdateStatusTracker, UpdateInstallerConfig],
    UpdateInstaller,
]
FirmwareRefresherFactory = Callable[
    [UpdateCommandExecutor, UpdateStatusTracker, Path, float],
    FirmwareRefresher,
]
UsbInternetOrchestratorFactory = Callable[
    [UsbInternetStatusService, UpdateCommandExecutor, UpdateStatusTracker, UpdateWifiConfig],
    UpdateUsbInternetOrchestrator,
]


def _default_command_executor(
    runner: CommandRunner,
    tracker: UpdateStatusTracker,
) -> UpdateCommandExecutor:
    return UpdateCommandExecutor(runner=runner, tracker=tracker)


def _default_wifi_orchestrator(
    commands: UpdateCommandExecutor,
    tracker: UpdateStatusTracker,
    config: UpdateWifiConfig,
) -> UpdateWifiOrchestrator:
    return UpdateWifiOrchestrator(commands=commands, tracker=tracker, config=config)


def _default_installer(
    commands: UpdateCommandExecutor,
    tracker: UpdateStatusTracker,
    config: UpdateInstallerConfig,
) -> UpdateInstaller:
    return UpdateInstaller(commands=commands, tracker=tracker, config=config)


def _default_firmware_refresher(
    commands: UpdateCommandExecutor,
    tracker: UpdateStatusTracker,
    repo: Path,
    timeout_s: float,
) -> FirmwareRefresher:
    return FirmwareRefresher(commands=commands, tracker=tracker, repo=repo, timeout_s=timeout_s)


def _default_usb_internet_orchestrator(
    status_service: UsbInternetStatusService,
    commands: UpdateCommandExecutor,
    tracker: UpdateStatusTracker,
    config: UpdateWifiConfig,
) -> UpdateUsbInternetOrchestrator:
    return UpdateUsbInternetOrchestrator(
        status_service=status_service,
        commands=commands,
        tracker=tracker,
        config=config,
    )


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
        command_executor_factory: CommandExecutorFactory = _default_command_executor,
        wifi_orchestrator_factory: WifiOrchestratorFactory = _default_wifi_orchestrator,
        installer_factory: InstallerFactory = _default_installer,
        firmware_refresher_factory: FirmwareRefresherFactory = _default_firmware_refresher,
        usb_internet_service: UsbInternetStatusService | None = None,
        usb_internet_orchestrator_factory: UsbInternetOrchestratorFactory = (
            _default_usb_internet_orchestrator
        ),
    ) -> None:
        self._runner = runner or CommandRunner()
        self._repo_path = repo_path or os.environ.get("VIBESENSOR_REPO_PATH", "/opt/VibeSensor")
        self._repo = Path(self._repo_path)
        self._ap_con_name = ap_con_name
        self._wifi_ifname = wifi_ifname
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

        # Store factories for collaborator construction.
        self._command_executor_factory = command_executor_factory
        self._wifi_orchestrator_factory = wifi_orchestrator_factory
        self._installer_factory = installer_factory
        self._firmware_refresher_factory = firmware_refresher_factory
        self._usb_internet_service = usb_internet_service or UsbInternetStatusService(
            runner=self._runner
        )
        self._usb_internet_orchestrator_factory = usb_internet_orchestrator_factory

        self._lifecycle = UpdateJobLifecycleHandler(
            tracker=self._tracker,
            repo=self._repo,
            wifi_factory=self._build_wifi_orchestrator,
            logger=LOGGER,
        )
        self._recovery = InterruptedUpdateRecovery(
            tracker=self._tracker,
            wifi_factory=self._build_wifi_orchestrator,
        )

        # Build config objects once — shared by workflow, snapshot, and rollback.
        self._installer_config = UpdateInstallerConfig(
            repo=self._repo,
            rollback_dir=self._rollback_dir,
            reinstall_timeout_s=REINSTALL_OP_TIMEOUT_S,
            firmware_refresh_timeout_s=ESP_FIRMWARE_REFRESH_TIMEOUT_S,
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
        commands = self._build_command_executor()
        workflow = UpdateWorkflow(
            tracker=self._tracker,
            commands=commands,
            wifi=self._build_wifi_orchestrator(commands=commands),
            usb_internet=self._build_usb_internet_orchestrator(commands=commands),
            installer=self._build_installer(commands),
            firmware_refresher=self._build_firmware_refresher(commands=commands),
            cancel_requested=self._executor.cancel_requested,
            validation_config=self._validation_config,
            rollback_dir=self._rollback_dir,
            service_name=UPDATE_SERVICE_NAME,
            restart_unit=UPDATE_RESTART_UNIT,
        )
        await workflow.execute(request)

    def _build_command_executor(self) -> UpdateCommandExecutor:
        return self._command_executor_factory(self._runner, self._tracker)

    def _build_wifi_orchestrator(
        self,
        *,
        commands: UpdateCommandExecutor | None = None,
    ) -> UpdateWifiOrchestrator:
        wifi_config = self._build_wifi_config()
        return self._wifi_orchestrator_factory(
            commands or self._build_command_executor(),
            self._tracker,
            wifi_config,
        )

    def _build_wifi_config(self) -> UpdateWifiConfig:
        return build_default_wifi_config(
            ap_con_name=self._ap_con_name,
            wifi_ifname=self._wifi_ifname,
        )

    def _build_usb_internet_orchestrator(
        self,
        *,
        commands: UpdateCommandExecutor | None = None,
    ) -> UpdateUsbInternetOrchestrator:
        return self._usb_internet_orchestrator_factory(
            self._usb_internet_service,
            commands or self._build_command_executor(),
            self._tracker,
            self._build_wifi_config(),
        )

    def _build_installer(
        self,
        commands: UpdateCommandExecutor,
    ) -> UpdateInstaller:
        return self._installer_factory(commands, self._tracker, self._installer_config)

    def _build_firmware_refresher(
        self,
        *,
        commands: UpdateCommandExecutor | None = None,
    ) -> FirmwareRefresher:
        return self._firmware_refresher_factory(
            commands or self._build_command_executor(),
            self._tracker,
            self._repo,
            self._installer_config.firmware_refresh_timeout_s,
        )

    async def _snapshot_for_rollback(self) -> bool:
        commands = self._build_command_executor()
        installer = self._build_installer(commands)
        return await installer.snapshot_for_rollback()

    async def _rollback(self) -> bool:
        commands = self._build_command_executor()
        installer = self._build_installer(commands)
        return await installer.rollback()
