from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.shared.exceptions import (
    UpdatePreparationError,
    UpdateReleaseError,
    UpdateTransportError,
)
from vibesensor.use_cases.updates.coordinator import UpdateCoordinator
from vibesensor.use_cases.updates.models import (
    UpdateExecutionOutcome,
    UpdateRequest,
    UpdateTransport,
)
from vibesensor.use_cases.updates.preparation import PreparedUpdateSession


def _wifi_request(ssid: str = "TestNet", password: str = "pass123") -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid=ssid,
        password=password,
    )


def _build_coordinator(
    tmp_path: Path,
) -> tuple[
    UpdateCoordinator,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    preparation = MagicMock()
    preparation.prepare = AsyncMock()
    release_planner = MagicMock()
    release_planner.plan = AsyncMock()
    workflow_executor = MagicMock()
    workflow_executor.execute = AsyncMock()
    coordinator = UpdateCoordinator(
        preparation=preparation,
        release_planner=release_planner,
        workflow_executor=workflow_executor,
    )
    return coordinator, preparation, release_planner, workflow_executor


@pytest.mark.asyncio
async def test_execute_stops_after_validation_failure(tmp_path: Path) -> None:
    (
        coordinator,
        preparation,
        release_planner,
        workflow_executor,
    ) = _build_coordinator(tmp_path)
    request = _wifi_request()

    preparation.prepare.side_effect = UpdatePreparationError("validation failed")

    with pytest.raises(UpdatePreparationError, match="validation failed"):
        await coordinator.execute(request)
    preparation.prepare.assert_awaited_once_with(request)
    release_planner.plan.assert_not_awaited()
    workflow_executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_stops_when_transport_cannot_prepare(tmp_path: Path) -> None:
    (
        coordinator,
        preparation,
        release_planner,
        workflow_executor,
    ) = _build_coordinator(tmp_path)
    request = _wifi_request()
    preparation.prepare.side_effect = UpdateTransportError("transport failed")

    with pytest.raises(UpdateTransportError, match="transport failed"):
        await coordinator.execute(request)

    preparation.prepare.assert_awaited_once_with(request)
    release_planner.plan.assert_not_awaited()
    workflow_executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_delegates_release_plan_and_execution(tmp_path: Path) -> None:
    (
        coordinator,
        preparation,
        release_planner,
        workflow_executor,
    ) = _build_coordinator(tmp_path)
    request = _wifi_request()
    release_plan = object()
    preparation.prepare.return_value = PreparedUpdateSession(
        current_version="2026.4.3",
    )
    release_planner.plan.return_value = release_plan
    workflow_executor.execute.return_value = UpdateExecutionOutcome.installed

    outcome = await coordinator.execute(request)

    assert outcome == UpdateExecutionOutcome.installed
    preparation.prepare.assert_awaited_once_with(request)
    release_planner.plan.assert_awaited_once_with("2026.4.3")
    workflow_executor.execute.assert_awaited_once_with(release_plan)


@pytest.mark.asyncio
async def test_execute_propagates_release_plan_failure(tmp_path: Path) -> None:
    (
        coordinator,
        preparation,
        release_planner,
        workflow_executor,
    ) = _build_coordinator(tmp_path)
    request = _wifi_request()
    preparation.prepare.return_value = PreparedUpdateSession(
        current_version="2026.4.3",
    )
    release_planner.plan.side_effect = UpdateReleaseError("release check failed")

    with pytest.raises(UpdateReleaseError, match="release check failed"):
        await coordinator.execute(request)
    preparation.prepare.assert_awaited_once_with(request)
    release_planner.plan.assert_awaited_once_with("2026.4.3")
    workflow_executor.execute.assert_not_awaited()
