"""Execute the canonical install path for one discovered server release."""

from __future__ import annotations

from typing import TYPE_CHECKING

from vibesensor.use_cases.updates.firmware import FirmwareRefresher
from vibesensor.use_cases.updates.release_deployment import (
    UpdateReleaseDeploymentCoordinator,
)
from vibesensor.use_cases.updates.release_staging import ServerReleaseStager

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.releases.release_fetcher import ReleaseInfo
    from vibesensor.use_cases.updates.status import UpdateStatusTracker

__all__ = ["ServerReleaseExecutionCoordinator"]


class ServerReleaseExecutionCoordinator:
    """Own staged release download, firmware refresh policy, and deployment handoff."""

    __slots__ = ("_deployment", "_firmware_refresher", "_stager", "_status")

    def __init__(
        self,
        *,
        stager: ServerReleaseStager,
        firmware_refresher: FirmwareRefresher,
        deployment: UpdateReleaseDeploymentCoordinator,
        status: UpdateStatusTracker,
    ) -> None:
        self._stager = stager
        self._firmware_refresher = firmware_refresher
        self._deployment = deployment
        self._status = status

    async def execute(self, release: ReleaseInfo) -> None:
        async with self._stager.stage(release) as staged_release:
            refresh_result = await self._firmware_refresher.refresh_esp_firmware(
                pinned_tag=staged_release.release.tag,
            )
            if not refresh_result.succeeded:
                self._status.add_issue(
                    refresh_result.phase,
                    refresh_result.message,
                    refresh_result.detail,
                )
                self._status.log(
                    "ESP firmware refresh failed; continuing with existing cache",
                )
            await self._deployment.deploy(staged_release)
