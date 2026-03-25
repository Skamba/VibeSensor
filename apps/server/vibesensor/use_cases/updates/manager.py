"""Public updater facade over focused update subsystems."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path

from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.installer import UpdateInstaller, UpdateInstallerConfig
from vibesensor.use_cases.updates.job_executor import UpdateJobExecutor
from vibesensor.use_cases.updates.job_lifecycle import UpdateJobLifecycleHandler
from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdatePhase,
    UpdateRequest,
    UpdateValidationConfig,
    validate_update_request,
)
from vibesensor.use_cases.updates.recovery import InterruptedUpdateRecovery
from vibesensor.use_cases.updates.releases import (
    check_for_update,
    download_release,
    verify_download,
)
from vibesensor.use_cases.updates.runner import CommandRunner, UpdateCommandExecutor
from vibesensor.use_cases.updates.status import (
    UpdateStateStore,
    UpdateStatusTracker,
    collect_runtime_details,
)
from vibesensor.use_cases.updates.validation import (
    MIN_FREE_DISK_BYTES,
    validate_prerequisites,
)
from vibesensor.use_cases.updates.wifi import (
    UpdateWifiOrchestrator,
    build_default_wifi_config,
)

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

    def start(self, ssid: str, password: str) -> None:
        request = validate_update_request(ssid, password)
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
            else UpdateRequest(ssid=request_or_ssid, password=password or "")
        )
        commands = self._build_command_executor()
        tracker = self._tracker
        wifi = self._build_wifi_orchestrator(commands=commands)
        installer = UpdateInstaller(
            commands=commands,
            tracker=tracker,
            config=self._installer_config,
        )
        firmware_refresher = self._build_firmware_refresher(commands=commands)
        cancel_requested = self._executor.cancel_requested

        if not await validate_prerequisites(
            commands=commands,
            tracker=tracker,
            config=self._validation_config,
            ssid=request.ssid,
        ):
            return
        if cancel_requested():
            return

        tracker.transition(UpdatePhase.stopping_hotspot)
        if not await wifi.stop_hotspot():
            return
        if cancel_requested():
            return

        tracker.transition(UpdatePhase.connecting_wifi)
        if not await wifi.connect_uplink(request.ssid, request.password):
            return
        if cancel_requested():
            return

        tracker.transition(UpdatePhase.checking)
        tracker.log("Checking for available updates...")
        from vibesensor import __version__ as current_version

        release_check = await check_for_update(tracker, self._rollback_dir, current_version)
        if release_check.failed:
            return
        if release_check.release is None:
            tracker.log(f"Already up-to-date (version={current_version})")
            await firmware_refresher.refresh_esp_firmware(pinned_tag=release_check.latest_tag)
            if cancel_requested():
                return
            if not await wifi.complete_update_success(
                "No server update needed; ESP firmware checked",
            ):
                return
            return

        tracker.log(f"Update available: {current_version} → {release_check.release.version}")
        if cancel_requested():
            return

        tracker.transition(UpdatePhase.downloading)
        tracker.log(f"Downloading release {release_check.release.tag}...")
        staging_dir = Path(tempfile.mkdtemp(prefix="vibesensor-update-"))
        try:
            wheel_path = await download_release(
                tracker,
                self._rollback_dir,
                release_check.release,
                staging_dir,
            )
            if wheel_path is None:
                return
            tracker.log(
                "Downloaded "
                f"{wheel_path.name} "
                f"(sha256={getattr(release_check.release, 'sha256', '')})",
            )
            if not await verify_download(tracker, release_check.release, wheel_path):
                return
            await firmware_refresher.refresh_esp_firmware(pinned_tag=release_check.release.tag)
            if cancel_requested():
                return

            tracker.transition(UpdatePhase.installing)
            tracker.log("Installing update...")
            rollback_ok = await installer.snapshot_for_rollback()
            if not rollback_ok:
                tracker.fail(
                    UpdatePhase.installing,
                    "Rollback snapshot could not be created",
                    "Install aborted before mutating the live environment",
                )
                return
            if not await installer.install_release(
                wheel_path,
                str(release_check.release.version),
            ):
                return
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

        if cancel_requested():
            return
        if not await wifi.complete_update_success("Update completed successfully"):
            return
        if await schedule_service_restart(
            commands=commands,
            tracker=tracker,
            service_name=UPDATE_SERVICE_NAME,
            restart_unit=UPDATE_RESTART_UNIT,
        ):
            return
        tracker.add_issue(
            "done",
            "Backend restart was not scheduled automatically",
            "Run 'sudo systemctl restart vibesensor.service' manually",
        )
        tracker.log("Automatic backend restart scheduling failed")

    def _build_command_executor(self) -> UpdateCommandExecutor:
        return UpdateCommandExecutor(runner=self._runner, tracker=self._tracker)

    def _build_wifi_orchestrator(
        self,
        *,
        commands: UpdateCommandExecutor | None = None,
    ) -> UpdateWifiOrchestrator:
        return UpdateWifiOrchestrator(
            commands=commands or self._build_command_executor(),
            tracker=self._tracker,
            config=build_default_wifi_config(
                ap_con_name=self._ap_con_name,
                wifi_ifname=self._wifi_ifname,
            ),
        )

    def _build_firmware_refresher(
        self,
        *,
        commands: UpdateCommandExecutor | None = None,
    ) -> FirmwareRefresher:
        return FirmwareRefresher(
            commands=commands or self._build_command_executor(),
            tracker=self._tracker,
            repo=self._repo,
            timeout_s=self._installer_config.firmware_refresh_timeout_s,
        )

    async def _snapshot_for_rollback(self) -> bool:
        commands = self._build_command_executor()
        installer = UpdateInstaller(
            commands=commands,
            tracker=self._tracker,
            config=self._installer_config,
        )
        return await installer.snapshot_for_rollback()

    async def _rollback(self) -> bool:
        commands = self._build_command_executor()
        installer = UpdateInstaller(
            commands=commands,
            tracker=self._tracker,
            config=self._installer_config,
        )
        return await installer.rollback()


# ---------------------------------------------------------------------------
# Service control
# ---------------------------------------------------------------------------


async def schedule_service_restart(
    *,
    commands: UpdateCommandExecutor,
    tracker: UpdateStatusTracker,
    service_name: str,
    restart_unit: str,
) -> bool:
    """Schedule a systemd restart of the backend service."""
    restart_attempts = [
        [
            "systemd-run",
            "--unit",
            restart_unit,
            "--on-active=2s",
            "systemctl",
            "restart",
            service_name,
        ],
        ["systemctl", "restart", service_name],
    ]
    for command in restart_attempts:
        rc, _, _ = await commands.run(
            command,
            phase="done",
            timeout=30,
            sudo=True,
        )
        if rc == 0:
            tracker.log("Scheduled backend service restart")
            return True
    return False
