from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibesensor.use_cases.updates.coordinator import UpdateCoordinator
from vibesensor.use_cases.updates.models import (
    UpdateExecutionOutcome,
    UpdateRequest,
    UpdateTransport,
    UpdateValidationConfig,
)
from vibesensor.use_cases.updates.status import UpdateStateStore, UpdateStatusTracker


def _wifi_request(ssid: str = "TestNet", password: str = "pass123") -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid=ssid,
        password=password,
    )


def _build_coordinator(
    tmp_path: Path,
    *,
    cancel_requested=lambda: False,
) -> tuple[
    UpdateCoordinator,
    UpdateStatusTracker,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    tracker = UpdateStatusTracker(state_store=UpdateStateStore(tmp_path / "state.json"))
    transport_controller = MagicMock()
    transport_controller.prepare = AsyncMock()
    release_planner = MagicMock()
    release_planner.plan = AsyncMock()
    workflow_executor = MagicMock()
    workflow_executor.execute = AsyncMock()
    coordinator = UpdateCoordinator(
        tracker=tracker,
        commands=MagicMock(),
        transport_controller=transport_controller,
        release_planner=release_planner,
        workflow_executor=workflow_executor,
        cancel_requested=cancel_requested,
        validation_config=UpdateValidationConfig(
            rollback_dir=tmp_path / "rollback",
            min_free_disk_bytes=1,
        ),
    )
    return coordinator, tracker, transport_controller, release_planner, workflow_executor


@pytest.mark.asyncio
async def test_execute_stops_after_validation_failure(tmp_path: Path) -> None:
    (
        coordinator,
        _tracker,
        transport_controller,
        release_planner,
        workflow_executor,
    ) = _build_coordinator(tmp_path)
    request = _wifi_request()

    with patch(
        "vibesensor.use_cases.updates.coordinator.validate_prerequisites",
        new=AsyncMock(return_value=False),
    ):
        outcome = await coordinator.execute(request)

    assert outcome == UpdateExecutionOutcome.aborted
    transport_controller.prepare.assert_not_awaited()
    release_planner.plan.assert_not_awaited()
    workflow_executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_stops_when_transport_cannot_prepare(tmp_path: Path) -> None:
    (
        coordinator,
        _tracker,
        transport_controller,
        release_planner,
        workflow_executor,
    ) = _build_coordinator(tmp_path)
    request = _wifi_request()
    transport_controller.prepare.return_value = None

    with patch(
        "vibesensor.use_cases.updates.coordinator.validate_prerequisites",
        new=AsyncMock(return_value=True),
    ):
        outcome = await coordinator.execute(request)

    assert outcome == UpdateExecutionOutcome.aborted
    transport_controller.prepare.assert_awaited_once_with(request)
    release_planner.plan.assert_not_awaited()
    workflow_executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_honors_cancellation_after_transport_prepare(tmp_path: Path) -> None:
    cancel_results = iter((False, True))
    (
        coordinator,
        _tracker,
        transport_controller,
        release_planner,
        workflow_executor,
    ) = _build_coordinator(
        tmp_path,
        cancel_requested=lambda: next(cancel_results),
    )
    request = _wifi_request()
    transport_session = object()
    transport_controller.prepare.return_value = transport_session

    with patch(
        "vibesensor.use_cases.updates.coordinator.validate_prerequisites",
        new=AsyncMock(return_value=True),
    ):
        outcome = await coordinator.execute(request)

    assert outcome == UpdateExecutionOutcome.aborted
    transport_controller.prepare.assert_awaited_once_with(request)
    release_planner.plan.assert_not_awaited()
    workflow_executor.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_delegates_release_plan_and_execution(tmp_path: Path) -> None:
    (
        coordinator,
        _tracker,
        transport_controller,
        release_planner,
        workflow_executor,
    ) = _build_coordinator(tmp_path)
    request = _wifi_request()
    transport_session = object()
    release_plan = object()
    transport_controller.prepare.return_value = transport_session
    release_planner.plan.return_value = release_plan
    workflow_executor.execute.return_value = UpdateExecutionOutcome.installed

    with (
        patch(
            "vibesensor.use_cases.updates.coordinator.validate_prerequisites",
            new=AsyncMock(return_value=True),
        ),
        patch("vibesensor.__version__", "2026.4.3"),
    ):
        outcome = await coordinator.execute(request)

    assert outcome == UpdateExecutionOutcome.installed
    transport_controller.prepare.assert_awaited_once_with(request)
    release_planner.plan.assert_awaited_once_with("2026.4.3")
    workflow_executor.execute.assert_awaited_once_with(
        release_plan,
        transport_session=transport_session,
    )


@pytest.mark.asyncio
async def test_execute_stops_when_release_planner_returns_none(tmp_path: Path) -> None:
    (
        coordinator,
        _tracker,
        transport_controller,
        release_planner,
        workflow_executor,
    ) = _build_coordinator(tmp_path)
    request = _wifi_request()
    transport_controller.prepare.return_value = object()
    release_planner.plan.return_value = None

    with (
        patch(
            "vibesensor.use_cases.updates.coordinator.validate_prerequisites",
            new=AsyncMock(return_value=True),
        ),
        patch("vibesensor.__version__", "2026.4.3"),
    ):
        outcome = await coordinator.execute(request)

    assert outcome == UpdateExecutionOutcome.aborted
    release_planner.plan.assert_awaited_once_with("2026.4.3")
    workflow_executor.execute.assert_not_awaited()
