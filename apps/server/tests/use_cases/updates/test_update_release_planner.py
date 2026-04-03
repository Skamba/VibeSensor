from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.use_cases.updates.models import (
    UpdatePhase,
    UpdateRequest,
    UpdateTransport,
)
from vibesensor.use_cases.updates.release_planner import (
    InstallServerReleasePlan,
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


@pytest.mark.asyncio
async def test_plan_returns_refresh_only_plan_when_no_server_update_is_needed(
    tmp_path: Path,
) -> None:
    planner, tracker, resolver = _planner(tmp_path)
    resolver.resolve.return_value = SimpleNamespace(
        failed=False,
        release=None,
        latest_tag="server-v2026.4.3",
    )

    plan = await planner.plan("2026.4.3")

    assert isinstance(plan, RefreshFirmwarePlan)
    assert plan.current_version == "2026.4.3"
    assert plan.latest_tag == "server-v2026.4.3"
    assert tracker.status.phase.value == "checking"
    assert any("Already up-to-date" in line for line in tracker.status.log_tail)


@pytest.mark.asyncio
async def test_plan_returns_install_plan_when_server_update_is_available(tmp_path: Path) -> None:
    planner, tracker, resolver = _planner(tmp_path)
    release = SimpleNamespace(version="2026.4.4", tag="server-v2026.4.4")
    resolver.resolve.return_value = SimpleNamespace(
        failed=False,
        release=release,
        latest_tag="server-v2026.4.4",
    )

    plan = await planner.plan("2026.4.3")

    assert isinstance(plan, InstallServerReleasePlan)
    assert plan.current_version == "2026.4.3"
    assert plan.release is release
    assert tracker.status.phase.value == "checking"
    assert any("Update available: 2026.4.3 → 2026.4.4" in line for line in tracker.status.log_tail)


@pytest.mark.asyncio
async def test_plan_returns_none_when_release_resolution_failed(tmp_path: Path) -> None:
    planner, tracker, resolver = _planner(tmp_path)
    resolver.resolve.return_value = SimpleNamespace(
        failed=True,
        release=None,
        latest_tag="server-v2026.4.3",
    )

    plan = await planner.plan("2026.4.3")

    assert plan is None
    assert tracker.status.phase.value == "checking"
