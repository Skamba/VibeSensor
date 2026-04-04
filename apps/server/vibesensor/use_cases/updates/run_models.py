"""Canonical run-scoped updater models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.releases.release_fetcher import ReleaseInfo
    from vibesensor.use_cases.updates.transport_sessions import ManagedUpdateTransportSession

__all__ = [
    "InstallServerReleasePlan",
    "PlannedUpdateRun",
    "PreparedUpdateRun",
    "RefreshFirmwarePlan",
    "ReleaseExecutionPlan",
]


@dataclass(frozen=True, slots=True)
class PreparedUpdateRun:
    """Validated updater state with one prepared transport session."""

    current_version: str
    transport_session: ManagedUpdateTransportSession


@dataclass(frozen=True, slots=True)
class RefreshFirmwarePlan:
    """Execution plan for runs that only need firmware refresh and success finalization."""

    latest_tag: str


@dataclass(frozen=True, slots=True)
class InstallServerReleasePlan:
    """Execution plan for runs that must stage and install a server release."""

    release: ReleaseInfo


type ReleaseExecutionPlan = RefreshFirmwarePlan | InstallServerReleasePlan


@dataclass(frozen=True, slots=True)
class PlannedUpdateRun:
    """Prepared updater run paired with the release work chosen for execution."""

    prepared: PreparedUpdateRun
    execution_plan: ReleaseExecutionPlan
