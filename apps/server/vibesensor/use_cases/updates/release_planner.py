"""Release-planning boundary for one update workflow run."""

from __future__ import annotations

from typing import TYPE_CHECKING

from vibesensor.use_cases.updates.models import UpdatePhase
from vibesensor.use_cases.updates.release_resolution import ServerReleaseResolver
from vibesensor.use_cases.updates.run_models import (
    InstallServerReleasePlan,
    PlannedUpdateRun,
    PreparedUpdateRun,
    RefreshFirmwarePlan,
)

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.status import UpdateStatusTracker

__all__ = ["UpdateReleasePlanner"]


class UpdateReleasePlanner:
    """Interpret resolved release state into one canonical execution plan."""

    __slots__ = ("_resolver", "_status")

    def __init__(
        self,
        *,
        status: UpdateStatusTracker,
        resolver: ServerReleaseResolver,
    ) -> None:
        self._status = status
        self._resolver = resolver

    async def plan(self, prepared: PreparedUpdateRun) -> PlannedUpdateRun:
        current_version = prepared.current_version
        self._status.transition(UpdatePhase.checking)
        self._status.log("Checking for available updates...")

        resolution = await self._resolver.resolve(current_version)
        if resolution.release is None:
            self._status.log(f"Already up-to-date (version={current_version})")
            return PlannedUpdateRun(
                prepared=prepared,
                execution_plan=RefreshFirmwarePlan(
                    latest_tag=resolution.latest_tag,
                ),
            )

        self._status.log(
            f"Update available: {current_version} → {resolution.release.version}",
        )
        return PlannedUpdateRun(
            prepared=prepared,
            execution_plan=InstallServerReleasePlan(
                release=resolution.release,
            ),
        )
