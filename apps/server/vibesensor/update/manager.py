"""Public updater facade over focused update subsystems."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from ..json_types import JsonObject
from .installer import UpdateInstaller, UpdateInstallerConfig
from .models import UpdateJobStatus, UpdatePhase, UpdateRequest, UpdateState
from .releases import UpdateReleaseConfig, UpdateReleaseService
from .runner import CommandRunner, UpdateCommandExecutor
from .status import UpdateRuntimeDetailsCollector, UpdateStateStore, UpdateStatusTracker
from .wifi import (
    DNS_PROBE_HOST,
    DNS_READY_MIN_WAIT_S,
    DNS_RETRY_INTERVAL_S,
    HOTSPOT_RESTORE_DELAY_S,
    HOTSPOT_RESTORE_RETRIES,
    NMCLI_TIMEOUT_S,
    UPLINK_CONNECT_RETRIES,
    UPLINK_CONNECT_WAIT_S,
    UPLINK_CONNECTION_NAME,
    UPLINK_FALLBACK_DNS,
    UpdateWifiConfig,
    UpdateWifiController,
    parse_wifi_diagnostics,
)
from .workflow import (
    UpdatePrerequisiteValidator,
    UpdateServiceControlConfig,
    UpdateServiceController,
    UpdateValidationConfig,
    UpdateWorkflow,
)

LOGGER = logging.getLogger(__name__)

UPDATE_TIMEOUT_S = 600
REINSTALL_OP_TIMEOUT_S = 180
MIN_FREE_DISK_BYTES = 200 * 1024 * 1024
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
        server_repo: str | None = None,
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
        self._server_repo = server_repo or os.environ.get("VIBESENSOR_SERVER_REPO", "")
        self._state_store = state_store or UpdateStateStore()
        loaded = self._state_store.load()
        self._tracker = UpdateStatusTracker(
            state_store=self._state_store,
            status=loaded if loaded is not None else UpdateJobStatus(),
        )
        self._runtime_details = UpdateRuntimeDetailsCollector(repo=self._repo)
        self._tracker.set_runtime(self._collect_runtime_details())
        self._status = self._tracker.status
        self._task: asyncio.Task[None] | None = None
        self._cancel_event = asyncio.Event()

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
        self._release_config = UpdateReleaseConfig(
            rollback_dir=self._rollback_dir,
            server_repo=self._server_repo,
        )
        self._service_control_config = UpdateServiceControlConfig(
            service_name=UPDATE_SERVICE_NAME,
            restart_unit=UPDATE_RESTART_UNIT,
        )

    @property
    def status(self) -> UpdateJobStatus:
        return self._tracker.status

    @property
    def job_task(self) -> asyncio.Task[None] | None:
        return self._task

    def start(self, ssid: str, password: str) -> None:
        ssid = ssid.strip()
        if not ssid or len(ssid) > 64:
            raise ValueError("SSID must be 1-64 characters")
        if password and len(password) > 128:
            raise ValueError("Password must be at most 128 characters")
        if self._task is not None and not self._task.done():
            raise RuntimeError("Update already in progress")
        self._cancel_event.clear()
        self._tracker.start_job(ssid)
        self._status = self._tracker.status
        self._tracker.track_secret(password)
        request = UpdateRequest(ssid=ssid, password=password)
        self._task = asyncio.get_running_loop().create_task(
            self._run_update(request),
            name="system-update",
        )

    def cancel(self) -> bool:
        if self._task is None or self._task.done():
            return False
        self._cancel_event.set()
        self._task.cancel()
        return True

    async def startup_recover(self) -> None:
        if (
            self._tracker.status.state != UpdateState.running
            or self._tracker.status.finished_at is not None
        ):
            return
        LOGGER.warning("Detected interrupted update job; marking as failed and cleaning up")
        self._tracker.mark_interrupted("Update interrupted by server restart")
        wifi = self._build_wifi_controller()

        self._tracker.log("startup_recover: cleaning up uplink connection")
        try:
            await wifi.cleanup_uplink()
        except Exception as exc:
            self._tracker.add_issue(
                "startup",
                "Failed to clean up uplink connection",
                str(exc),
            )

        self._tracker.log("startup_recover: restoring hotspot")
        try:
            restored = await wifi.restore_hotspot()
            if restored:
                self._tracker.log("startup_recover: hotspot restored successfully")
            else:
                self._tracker.add_issue(
                    "startup",
                    "Failed to restore hotspot after interrupted update",
                )
                self._tracker.log("startup_recover: hotspot restore failed")
        except Exception as exc:
            self._tracker.add_issue(
                "startup",
                "Hotspot restore error during recovery",
                str(exc),
            )
        self._tracker.persist()

    async def _run_update(
        self,
        request_or_ssid: UpdateRequest | str,
        password: str | None = None,
    ) -> None:
        try:
            await asyncio.wait_for(
                self._run_update_inner(request_or_ssid, password),
                timeout=UPDATE_TIMEOUT_S,
            )
        except TimeoutError:
            if hasattr(self, "_tracker"):
                self._tracker.fail("timeout", f"Update timed out after {UPDATE_TIMEOUT_S}s")
                self._tracker.log(f"Update timed out after {UPDATE_TIMEOUT_S}s")
        except asyncio.CancelledError:
            if hasattr(self, "_tracker"):
                self._tracker.fail("cancelled", "Update was cancelled")
                self._tracker.log("Update cancelled")
            raise
        except Exception as exc:
            if hasattr(self, "_tracker"):
                self._tracker.fail("unexpected", f"Unexpected error: {exc}")
            LOGGER.exception("update: unexpected error")
        finally:
            await self._cleanup_after_update()

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
        await self._build_workflow().run(request)

    async def _cleanup_after_update(self) -> None:
        tracker = self._tracker
        try:
            if tracker.status.state == UpdateState.running:
                tracker.transition(UpdatePhase.restoring_hotspot)
                tracker.log("Restoring hotspot...")
                await asyncio.shield(self._build_wifi_controller().restore_hotspot())
            tracker.clear_secrets()
            try:
                tracker.set_runtime(await asyncio.to_thread(self._collect_runtime_details))
                self._status = tracker.status
            except Exception:
                LOGGER.warning("Failed to collect runtime details", exc_info=True)
            try:
                diag_issues = await asyncio.to_thread(parse_wifi_diagnostics)
                tracker.extend_issues(diag_issues)
            except Exception:
                LOGGER.debug("Failed to parse Wi-Fi diagnostics", exc_info=True)
            tracker.finish_cleanup()
            self._status = tracker.status
        except Exception:
            tracker.clear_secrets()
            tracker.finish_cleanup()
            self._status = tracker.status
            LOGGER.warning("Update cleanup interrupted", exc_info=True)

    def _build_workflow(self) -> UpdateWorkflow:
        commands = self._build_command_executor()
        return UpdateWorkflow(
            tracker=self._tracker,
            validator=UpdatePrerequisiteValidator(
                commands=commands,
                tracker=self._tracker,
                config=self._validation_config,
            ),
            wifi=self._build_wifi_controller(commands=commands),
            releases=UpdateReleaseService(
                tracker=self._tracker,
                config=self._release_config,
            ),
            installer=UpdateInstaller(
                commands=commands,
                tracker=self._tracker,
                config=self._installer_config,
            ),
            services=UpdateServiceController(
                commands=commands,
                tracker=self._tracker,
                config=self._service_control_config,
            ),
            cancel_requested=self._cancel_event.is_set,
        )

    def _build_command_executor(self) -> UpdateCommandExecutor:
        return UpdateCommandExecutor(runner=self._runner, tracker=self._tracker)

    def _build_wifi_controller(
        self,
        *,
        commands: UpdateCommandExecutor | None = None,
    ) -> UpdateWifiController:
        return UpdateWifiController(
            commands=commands or self._build_command_executor(),
            tracker=self._tracker,
            config=UpdateWifiConfig(
                ap_con_name=self._ap_con_name,
                wifi_ifname=self._wifi_ifname,
                uplink_connection_name=UPLINK_CONNECTION_NAME,
                uplink_connect_wait_s=UPLINK_CONNECT_WAIT_S,
                uplink_connect_retries=UPLINK_CONNECT_RETRIES,
                uplink_fallback_dns=UPLINK_FALLBACK_DNS,
                dns_ready_min_wait_s=DNS_READY_MIN_WAIT_S,
                dns_retry_interval_s=DNS_RETRY_INTERVAL_S,
                dns_probe_host=DNS_PROBE_HOST,
                nmcli_timeout_s=NMCLI_TIMEOUT_S,
                hotspot_restore_retries=HOTSPOT_RESTORE_RETRIES,
                hotspot_restore_delay_s=HOTSPOT_RESTORE_DELAY_S,
            ),
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

    def _collect_runtime_details(self) -> JsonObject:
        return self._runtime_details.collect()
