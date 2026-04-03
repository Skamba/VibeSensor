from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.models import (
    UpdatePhase,
    UpdateRequest,
    UpdateTransport,
)
from vibesensor.use_cases.updates.preparation import PreparedUpdateWorkflow
from vibesensor.use_cases.updates.release_planner import (
    InstallServerReleasePlan,
    PlannedUpdateWorkflow,
    RefreshFirmwarePlan,
    UpdateReleasePlanner,
)
from vibesensor.use_cases.updates.status import UpdateStateStore, UpdateStatusTracker


def _planner(tmp_path: Path) -> tuple[UpdateReleasePlanner, UpdateStatusTracker, MagicMock]:
    tracker = UpdateStatusTracker(state_store=UpdateStateStore(tmp_path / "state.json"))
    tracker.start_job(
        UpdateRequest(
            transport=UpdateTransport.wifi,
            ssid="TestNet",
            password="secret",
        )
    )
    tracker.transition(UpdatePhase.connecting_usb_internet)
    resolver = MagicMock()
    resolver.resolve = AsyncMock()
    return UpdateReleasePlanner(tracker=tracker, resolver=resolver), tracker, resolver


def _prepared_workflow() -> PreparedUpdateWorkflow:
    return PreparedUpdateWorkflow(
        current_version="2026.4.3",
        transport_session=object(),
    )


@pytest.mark.asyncio
async def test_plan_returns_refresh_only_plan_when_no_server_update_is_needed(
    tmp_path: Path,
) -> None:
    planner, tracker, resolver = _planner(tmp_path)
    resolver.resolve.return_value = SimpleNamespace(
        release=None,
        latest_tag="server-v2026.4.3",
    )

    planned = await planner.plan(_prepared_workflow())

    assert isinstance(planned, PlannedUpdateWorkflow)
    assert isinstance(planned.execution_plan, RefreshFirmwarePlan)
    assert planned.execution_plan.current_version == "2026.4.3"
    assert planned.execution_plan.latest_tag == "server-v2026.4.3"
    assert tracker.status.phase.value == "checking"
    assert any("Already up-to-date" in line for line in tracker.status.log_tail)


@pytest.mark.asyncio
async def test_plan_returns_install_plan_when_server_update_is_available(tmp_path: Path) -> None:
    planner, tracker, resolver = _planner(tmp_path)
    release = SimpleNamespace(version="2026.4.4", tag="server-v2026.4.4")
    resolver.resolve.return_value = SimpleNamespace(
        release=release,
        latest_tag="server-v2026.4.4",
    )

    planned = await planner.plan(_prepared_workflow())

    assert isinstance(planned.execution_plan, InstallServerReleasePlan)
    assert planned.execution_plan.current_version == "2026.4.3"
    assert planned.execution_plan.release is release
    assert tracker.status.phase.value == "checking"
    assert any("Update available: 2026.4.3 → 2026.4.4" in line for line in tracker.status.log_tail)


@pytest.mark.asyncio
async def test_plan_propagates_release_resolution_failure(tmp_path: Path) -> None:
    planner, tracker, resolver = _planner(tmp_path)
    resolver.resolve.side_effect = UpdateReleaseError("release check failed")

    with pytest.raises(UpdateReleaseError, match="release check failed"):
        await planner.plan(_prepared_workflow())

    assert tracker.status.phase.value == "checking"
