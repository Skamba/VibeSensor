"""Deploy a staged server release into the live installation."""

from __future__ import annotations

from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.release_installation import UpdateReleaseInstallationCoordinator
from vibesensor.use_cases.updates.release_staging import StagedServerRelease


class UpdateReleaseDeployer:
    """Own the system-mutating part of an update after staging succeeds."""

    __slots__ = ("_firmware_refresher", "_installation")

    def __init__(
        self,
        *,
        installation: UpdateReleaseInstallationCoordinator,
        firmware_refresher: FirmwareRefresher,
    ) -> None:
        self._installation = installation
        self._firmware_refresher = firmware_refresher

    async def deploy(self, staged_release: StagedServerRelease) -> None:
        await self._firmware_refresher.refresh_esp_firmware(pinned_tag=staged_release.release.tag)
        await self._installation.install(staged_release)
