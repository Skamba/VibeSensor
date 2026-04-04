"""Install/rollback orchestration for staged server releases."""

from __future__ import annotations

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.installer import UpdateInstaller
from vibesensor.use_cases.updates.models import UpdatePhase
from vibesensor.use_cases.updates.release_staging import StagedServerRelease
from vibesensor.use_cases.updates.status import UpdateStatusTracker

__all__ = ["UpdateReleaseInstallationCoordinator"]


class UpdateReleaseInstallationCoordinator:
    """Own install-time snapshot, install, and rollback policy for staged releases."""

    __slots__ = ("_installer", "_status")

    def __init__(
        self,
        *,
        installer: UpdateInstaller,
        status: UpdateStatusTracker,
    ) -> None:
        self._installer = installer
        self._status = status

    async def install(self, staged_release: StagedServerRelease) -> None:
        self._status.transition(UpdatePhase.installing)
        self._status.log("Installing update...")
        if not await self._installer.snapshot_for_rollback():
            self._status.fail(
                UpdatePhase.installing.value,
                "Rollback snapshot could not be created",
                "Install aborted before mutating the live environment",
            )
            raise UpdateReleaseError("Rollback snapshot could not be created")

        install_result = await self._installer.install_release(
            staged_release.wheel_path,
            str(staged_release.release.version),
        )
        if install_result.succeeded:
            return
        if not install_result.rollback_required:
            raise UpdateReleaseError("Update install failed")

        self._status.log("Attempting rollback...")
        rollback_succeeded = await self._installer.rollback()
        if rollback_succeeded:
            raise UpdateReleaseError(
                "Update install failed; rollback restored the previous version",
            )
        raise UpdateReleaseError("Update install failed and rollback did not complete")
