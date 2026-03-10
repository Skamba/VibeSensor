"""Top-level updater workflow orchestration and prerequisite validation."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .installer import UpdateInstaller
from .models import UpdatePhase, UpdateRequest, UpdateState
from .releases import UpdateReleaseService
from .runner import UpdateCommandExecutor
from .status import UpdateStatusTracker
from .wifi import UpdateWifiController

# ---------------------------------------------------------------------------
# Prerequisite validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UpdateValidationConfig:
    rollback_dir: Path
    min_free_disk_bytes: int


class UpdatePrerequisiteValidator:
    """Validates tool availability, privilege access, and disk space."""

    __slots__ = ("_commands", "_config", "_tracker")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        tracker: UpdateStatusTracker,
        config: UpdateValidationConfig,
    ) -> None:
        self._commands = commands
        self._tracker = tracker
        self._config = config

    def _probe_rollback_dir(self) -> None:
        self._config.rollback_dir.mkdir(parents=True, exist_ok=True)
        probe_dir = self._config.rollback_dir
        probe_handle = tempfile.NamedTemporaryFile(
            prefix=".rollback-write-probe-",
            dir=probe_dir,
            delete=False,
        )
        probe_path = Path(probe_handle.name)
        try:
            probe_handle.write(b"ok")
            probe_handle.flush()
        finally:
            probe_handle.close()
        probe_path.unlink(missing_ok=True)

    async def validate(self, ssid: str) -> bool:
        self._tracker.log(f"Starting update with SSID: {ssid}")
        for tool in ("nmcli", "python3"):
            if not shutil.which(tool):
                self._tracker.fail("validating", f"Required tool not found: {tool}")
                return False

        if os.geteuid() != 0:
            rc, _, _ = await self._commands.run(
                ["sudo", "-n", "true"],
                phase="validating",
                timeout=5,
                sudo=False,
            )
            if rc != 0:
                self._tracker.fail(
                    "validating",
                    "Insufficient privileges",
                    "Cannot run sudo non-interactively. In dev/Docker "
                    "environments, hotspot management is not available.",
                )
                return False

        try:
            self._probe_rollback_dir()
        except OSError as exc:
            self._tracker.fail(
                "validating",
                "Rollback directory is not writable",
                f"{self._config.rollback_dir}: {exc}",
            )
            return False

        try:
            disk_check_path = self._config.rollback_dir.parent
            if not disk_check_path.exists():
                disk_check_path = Path("/var/lib") if Path("/var/lib").exists() else Path("/")
            free_bytes = shutil.disk_usage(disk_check_path).free
            if free_bytes < self._config.min_free_disk_bytes:
                free_mb = free_bytes // (1024 * 1024)
                min_mb = self._config.min_free_disk_bytes // (1024 * 1024)
                self._tracker.fail(
                    "validating",
                    f"Insufficient disk space: {free_mb} MiB free, {min_mb} MiB required",
                )
                return False
        except OSError as exc:
            self._tracker.fail(
                "validating",
                "Could not verify free disk space",
                str(exc),
            )
            return False

        return True


# ---------------------------------------------------------------------------
# Service control
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UpdateServiceControlConfig:
    service_name: str
    restart_unit: str


class UpdateServiceController:
    """Owns systemd drop-in management and restart scheduling."""

    __slots__ = ("_commands", "_config", "_tracker")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        tracker: UpdateStatusTracker,
        config: UpdateServiceControlConfig,
    ) -> None:
        self._commands = commands
        self._tracker = tracker
        self._config = config

    async def schedule_restart(self) -> bool:
        restart_attempts = [
            [
                "systemd-run",
                "--unit",
                self._config.restart_unit,
                "--on-active=2s",
                "systemctl",
                "restart",
                self._config.service_name,
            ],
            ["systemctl", "restart", self._config.service_name],
        ]
        for command in restart_attempts:
            rc, _, _ = await self._commands.run(
                command,
                phase="done",
                timeout=30,
                sudo=True,
            )
            if rc == 0:
                self._tracker.log("Scheduled backend service restart")
                return True
        return False


@dataclass(slots=True)
class UpdateWorkflow:
    tracker: UpdateStatusTracker
    validator: UpdatePrerequisiteValidator
    wifi: UpdateWifiController
    releases: UpdateReleaseService
    installer: UpdateInstaller
    services: UpdateServiceController
    cancel_requested: Callable[[], bool]

    async def run(self, request: UpdateRequest) -> None:
        if not await self.validator.validate(request.ssid):
            return
        if self.cancel_requested():
            return

        self.tracker.transition(UpdatePhase.stopping_hotspot)
        if not await self.wifi.stop_hotspot():
            return
        if self.cancel_requested():
            return

        self.tracker.transition(UpdatePhase.connecting_wifi)
        if not await self.wifi.connect_uplink(request.ssid, request.password):
            return
        if self.cancel_requested():
            return

        self.tracker.transition(UpdatePhase.checking)
        self.tracker.log("Checking for available updates...")
        from vibesensor import __version__ as current_version

        release_check = await self.releases.check_for_update(current_version)
        if release_check.failed:
            return
        if release_check.release is None:
            self.tracker.log(f"Already up-to-date (version={current_version})")
            await self.installer.refresh_esp_firmware(pinned_tag=release_check.latest_tag)
            if self.cancel_requested():
                return
            await self._complete_success("No server update needed; ESP firmware checked")
            return

        self.tracker.log(f"Update available: {current_version} → {release_check.release.version}")
        if self.cancel_requested():
            return

        self.tracker.transition(UpdatePhase.downloading)
        self.tracker.log(f"Downloading release {release_check.release.tag}...")
        staging_dir = Path(tempfile.mkdtemp(prefix="vibesensor-update-"))
        try:
            wheel_path = await self.releases.download(release_check.release, staging_dir)
            if wheel_path is None:
                return
            self.tracker.log(
                "Downloaded "
                f"{wheel_path.name} "
                f"(sha256={getattr(release_check.release, 'sha256', '')})",
            )
            if not await self.releases.verify_download(release_check.release, wheel_path):
                return
            await self.installer.refresh_esp_firmware(pinned_tag=release_check.release.tag)
            if self.cancel_requested():
                return

            self.tracker.transition(UpdatePhase.installing)
            self.tracker.log("Installing update...")
            rollback_ok = await self.installer.snapshot_for_rollback()
            if not rollback_ok:
                self.tracker.fail(
                    UpdatePhase.installing,
                    "Rollback snapshot could not be created",
                    "Install aborted before mutating the live environment",
                )
                return
            if not await self.installer.install_release(
                wheel_path,
                str(release_check.release.version),
            ):
                return
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

        if self.cancel_requested():
            return
        await self._complete_success("Update completed successfully")
        if await self.services.schedule_restart():
            return
        self.tracker.add_issue(
            "done",
            "Backend restart was not scheduled automatically",
            "Run 'sudo systemctl restart vibesensor.service' manually",
        )
        self.tracker.log("Automatic backend restart scheduling failed")

    async def _complete_success(self, message: str) -> None:
        self.tracker.transition(UpdatePhase.restoring_hotspot)
        self.tracker.log("Restoring hotspot...")
        restored = await self.wifi.restore_hotspot()
        if not restored:
            self.tracker.status.state = UpdateState.failed
            self.tracker.persist()
            return
        self.tracker.mark_success(message)
