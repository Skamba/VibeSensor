"""Deploy a staged server release into the live installation."""

from __future__ import annotations

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.installer import UpdateInstaller
from vibesensor.use_cases.updates.models import UpdatePhase
from vibesensor.use_cases.updates.release_staging import StagedServerRelease
from vibesensor.use_cases.updates.status import UpdateStatusTracker


class UpdateReleaseDeployer:
    """Own the system-mutating part of an update after staging succeeds."""

    __slots__ = ("_firmware_refresher", "_installer", "_tracker")

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        installer: UpdateInstaller,
        firmware_refresher: FirmwareRefresher,
    ) -> None:
        self._tracker = tracker
        self._installer = installer
        self._firmware_refresher = firmware_refresher

    async def deploy(self, staged_release: StagedServerRelease) -> None:
        await self._firmware_refresher.refresh_esp_firmware(pinned_tag=staged_release.release.tag)
        self._tracker.transition(UpdatePhase.installing)
        self._tracker.log("Installing update...")
        if not await self._installer.snapshot_for_rollback():
            self._tracker.fail(
                UpdatePhase.installing,
                "Rollback snapshot could not be created",
                "Install aborted before mutating the live environment",
            )
            raise UpdateReleaseError("Rollback snapshot could not be created")
        await self._installer.install_release(
            staged_release.wheel_path,
            str(staged_release.release.version),
        )
