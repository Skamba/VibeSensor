"""Release discovery, install orchestration, and restart scheduling for updates."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.installer import UpdateInstaller
from vibesensor.use_cases.updates.models import UpdatePhase
from vibesensor.use_cases.updates.releases import (
    UpdateReleaseCheck,
    check_for_update,
    download_release,
    verify_download,
)
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSession


class UpdateReleaseApplication:
    """Own the non-transport portion of an update run once uplink is ready."""

    __slots__ = (
        "_cancel_requested",
        "_commands",
        "_firmware_refresher",
        "_installer",
        "_restart_unit",
        "_rollback_dir",
        "_service_name",
        "_tracker",
    )

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        commands: UpdateCommandExecutor,
        installer: UpdateInstaller,
        firmware_refresher: FirmwareRefresher,
        cancel_requested: Callable[[], bool],
        rollback_dir: Path,
        service_name: str,
        restart_unit: str,
    ) -> None:
        self._tracker = tracker
        self._commands = commands
        self._installer = installer
        self._firmware_refresher = firmware_refresher
        self._cancel_requested = cancel_requested
        self._rollback_dir = rollback_dir
        self._service_name = service_name
        self._restart_unit = restart_unit

    async def execute(self, transport_session: UpdateTransportSession) -> None:
        """Check for updates and apply them after transport preparation succeeds."""

        self._tracker.transition(UpdatePhase.checking)
        self._tracker.log("Checking for available updates...")
        from vibesensor import __version__ as current_version

        release_check = await check_for_update(
            self._tracker,
            self._rollback_dir,
            current_version,
        )
        if release_check.failed:
            return
        if release_check.release is None:
            await self._handle_already_up_to_date(
                transport_session,
                current_version=current_version,
                latest_tag=release_check.latest_tag,
            )
            return

        self._tracker.log(
            f"Update available: {current_version} → {release_check.release.version}",
        )
        if self._cancelled():
            return
        await self._download_and_install(transport_session, release_check)

    async def _handle_already_up_to_date(
        self,
        transport_session: UpdateTransportSession,
        *,
        current_version: str,
        latest_tag: str,
    ) -> None:
        self._tracker.log(f"Already up-to-date (version={current_version})")
        await self._firmware_refresher.refresh_esp_firmware(pinned_tag=latest_tag)
        if self._cancelled():
            return
        await transport_session.complete_success("No server update needed; ESP firmware checked")

    async def _download_and_install(
        self,
        transport_session: UpdateTransportSession,
        release_check: UpdateReleaseCheck,
    ) -> None:
        release = release_check.release
        assert release is not None  # noqa: S101
        self._tracker.transition(UpdatePhase.downloading)
        self._tracker.log(f"Downloading release {release.tag}...")
        staging_dir = Path(tempfile.mkdtemp(prefix="vibesensor-update-"))
        try:
            wheel_path = await download_release(
                self._tracker,
                self._rollback_dir,
                release,
                staging_dir,
            )
            if wheel_path is None:
                return
            self._tracker.log(
                f"Downloaded {wheel_path.name} (sha256={getattr(release, 'sha256', '')})",
            )
            if not await verify_download(self._tracker, release, wheel_path):
                return
            await self._firmware_refresher.refresh_esp_firmware(pinned_tag=release.tag)
            if self._cancelled():
                return
            if not await self._install(wheel_path, str(release.version)):
                return
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

        if self._cancelled():
            return
        await self._finalize(transport_session)

    async def _install(self, wheel_path: Path, version: str) -> bool:
        self._tracker.transition(UpdatePhase.installing)
        self._tracker.log("Installing update...")
        if not await self._installer.snapshot_for_rollback():
            self._tracker.fail(
                UpdatePhase.installing,
                "Rollback snapshot could not be created",
                "Install aborted before mutating the live environment",
            )
            return False
        return await self._installer.install_release(wheel_path, version)

    async def _finalize(self, transport_session: UpdateTransportSession) -> None:
        if not await transport_session.complete_success("Update completed successfully"):
            return
        if await schedule_service_restart(
            commands=self._commands,
            tracker=self._tracker,
            service_name=self._service_name,
            restart_unit=self._restart_unit,
        ):
            return
        self._tracker.add_issue(
            "done",
            "Backend restart was not scheduled automatically",
            "Run 'sudo systemctl restart vibesensor.service' manually",
        )
        self._tracker.log("Automatic backend restart scheduling failed")

    def _cancelled(self) -> bool:
        return self._cancel_requested()


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
