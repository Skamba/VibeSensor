"""Release-planning boundary for one update workflow run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.use_cases.updates.models import UpdatePhase
from vibesensor.use_cases.updates.preparation import PreparedUpdateWorkflow
from vibesensor.use_cases.updates.release_resolution import ServerReleaseResolver
from vibesensor.use_cases.updates.transport_coordinator import PreparedUpdateTransport

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.releases.release_fetcher import ReleaseInfo
    from vibesensor.use_cases.updates.status import UpdateStatusController, UpdateStatusRecorder

__all__ = [
    "InstallServerReleasePlan",
    "PlannedUpdateWorkflow",
    "RefreshFirmwarePlan",
    "ReleaseExecutionPlan",
    "UpdateReleasePlanner",
]


@dataclass(frozen=True, slots=True)
class RefreshFirmwarePlan:
    """Execution plan for runs that only need firmware refresh and transport success."""

    current_version: str
    latest_tag: str


@dataclass(frozen=True, slots=True)
class InstallServerReleasePlan:
    """Execution plan for runs that must stage and install a new server release."""

    current_version: str
    release: ReleaseInfo


type ReleaseExecutionPlan = RefreshFirmwarePlan | InstallServerReleasePlan


@dataclass(frozen=True, slots=True)
class PlannedUpdateWorkflow:
    """Release plan coupled to the already-prepared transport session."""

    transport: PreparedUpdateTransport
    execution_plan: ReleaseExecutionPlan


class UpdateReleasePlanner:
    """Interpret resolved release state into one canonical execution plan."""

    __slots__ = ("_resolver", "_status_controller", "_status_recorder")

    def __init__(
        self,
        *,
        status_controller: UpdateStatusController,
        status_recorder: UpdateStatusRecorder,
        resolver: ServerReleaseResolver,
    ) -> None:
        self._status_controller = status_controller
        self._status_recorder = status_recorder
        self._resolver = resolver

    async def plan(self, prepared: PreparedUpdateWorkflow) -> PlannedUpdateWorkflow:
        current_version = prepared.current_version
        self._status_controller.transition(UpdatePhase.checking)
        self._status_recorder.log("Checking for available updates...")

        resolution = await self._resolver.resolve(current_version)
        if resolution.release is None:
            self._status_recorder.log(f"Already up-to-date (version={current_version})")
            return PlannedUpdateWorkflow(
                transport=prepared.transport,
                execution_plan=RefreshFirmwarePlan(
                    current_version=current_version,
                    latest_tag=resolution.latest_tag,
                ),
            )

        self._status_recorder.log(
            f"Update available: {current_version} → {resolution.release.version}",
        )
        return PlannedUpdateWorkflow(
            transport=prepared.transport,
            execution_plan=InstallServerReleasePlan(
                current_version=current_version,
                release=resolution.release,
            ),
        )
