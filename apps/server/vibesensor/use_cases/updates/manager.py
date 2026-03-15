"""Public updater facade over focused update subsystems."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path

from vibesensor.domain.updates.models import (
    UpdateJobStatus,
    UpdatePhase,
    UpdateRequest,
    UpdateState,
    UpdateValidationConfig,
)

from .installer import UpdateInstaller, UpdateInstallerConfig
from .releases import check_for_update, download_release, verify_download
from .runner import CommandRunner, UpdateCommandExecutor
from .status import UpdateStateStore, UpdateStatusTracker, collect_runtime_details
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
        commands = self._build_command_executor()
        tracker = self._tracker
        wifi = self._build_wifi_controller(commands=commands)
        installer = UpdateInstaller(
            commands=commands,
            tracker=tracker,
            config=self._installer_config,
        )
        cancel_requested = self._cancel_event.is_set

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
            await installer.refresh_esp_firmware(pinned_tag=release_check.latest_tag)
            if cancel_requested():
                return
            await self._complete_update_success(
                tracker,
                wifi,
                "No server update needed; ESP firmware checked",
            )
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
            await installer.refresh_esp_firmware(pinned_tag=release_check.release.tag)
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
        await self._complete_update_success(tracker, wifi, "Update completed successfully")
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

    async def _complete_update_success(
        self,
        tracker: UpdateStatusTracker,
        wifi: UpdateWifiController,
        message: str,
    ) -> None:
        tracker.transition(UpdatePhase.restoring_hotspot)
        tracker.log("Restoring hotspot...")
        restored = await wifi.restore_hotspot()
        if not restored:
            tracker.status.state = UpdateState.failed
            tracker.persist()
            return
        tracker.mark_success(message)

    async def _cleanup_after_update(self) -> None:
        tracker = self._tracker
        try:
            if tracker.status.state == UpdateState.running:
                tracker.transition(UpdatePhase.restoring_hotspot)
                tracker.log("Restoring hotspot...")
                await asyncio.shield(self._build_wifi_controller().restore_hotspot())
            tracker.clear_secrets()
            try:
                tracker.set_runtime(await asyncio.to_thread(collect_runtime_details, self._repo))
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


# ---------------------------------------------------------------------------
# Prerequisite validation
# ---------------------------------------------------------------------------


def _probe_rollback_dir(rollback_dir: Path) -> None:
    rollback_dir.mkdir(parents=True, exist_ok=True)
    probe_handle = tempfile.NamedTemporaryFile(
        prefix=".rollback-write-probe-",
        dir=rollback_dir,
        delete=False,
    )
    probe_path = Path(probe_handle.name)
    try:
        probe_handle.write(b"ok")
        probe_handle.flush()
    finally:
        probe_handle.close()
    probe_path.unlink(missing_ok=True)


async def validate_prerequisites(
    *,
    commands: UpdateCommandExecutor,
    tracker: UpdateStatusTracker,
    config: UpdateValidationConfig,
    ssid: str,
) -> bool:
    """Validate tool availability, privilege access, and disk space."""
    tracker.log(f"Starting update with SSID: {ssid}")
    for tool in ("nmcli", "python3"):
        if not shutil.which(tool):
            tracker.fail("validating", f"Required tool not found: {tool}")
            return False

    if os.geteuid() != 0:
        rc, _, _ = await commands.run(
            ["sudo", "-n", "true"],
            phase="validating",
            timeout=5,
            sudo=False,
        )
        if rc != 0:
            tracker.fail(
                "validating",
                "Insufficient privileges",
                "Cannot run sudo non-interactively. In dev/Docker "
                "environments, hotspot management is not available.",
            )
            return False

    try:
        _probe_rollback_dir(config.rollback_dir)
    except OSError as exc:
        tracker.fail(
            "validating",
            "Rollback directory is not writable",
            f"{config.rollback_dir}: {exc}",
        )
        return False

    try:
        disk_check_path = config.rollback_dir.parent
        if not disk_check_path.exists():
            disk_check_path = Path("/var/lib") if Path("/var/lib").exists() else Path("/")
        free_bytes = shutil.disk_usage(disk_check_path).free
        if free_bytes < config.min_free_disk_bytes:
            free_mb = free_bytes // (1024 * 1024)
            min_mb = config.min_free_disk_bytes // (1024 * 1024)
            tracker.fail(
                "validating",
                f"Insufficient disk space: {free_mb} MiB free, {min_mb} MiB required",
            )
            return False
    except OSError as exc:
        tracker.fail(
            "validating",
            "Could not verify free disk space",
            str(exc),
        )
        return False

    return True


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
