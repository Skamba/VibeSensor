from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.shared.exceptions import UpdatePreparationError, UpdateReleaseError
from vibesensor.use_cases.updates.manager import UpdateManager
from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdateRequest,
    UpdateState,
    UpdateTransport,
)
from vibesensor.use_cases.updates.preparation import PreparedUpdateWorkflow
from vibesensor.use_cases.updates.workflow import UpdateWorkflow
from vibesensor.use_cases.updates.workflow_runner import UpdateWorkflowContext


def _wifi_request(ssid: str = "TestNet", password: str = "pass123") -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid=ssid,
        password=password,
    )


def _build_workflow() -> tuple[UpdateWorkflow, AsyncMock, AsyncMock, AsyncMock]:
    preparation = MagicMock()
    preparation.prepare = AsyncMock()
    release_planner = MagicMock()
    release_planner.plan = AsyncMock()
    workflow_executor = MagicMock()
    workflow_executor.execute = AsyncMock()
    return (
        UpdateWorkflow(
            preparation=preparation,
            release_planner=release_planner,
            workflow_executor=workflow_executor,
        ),
        preparation.prepare,
        release_planner.plan,
        workflow_executor.execute,
    )


def _build_manager(
    *,
    status: UpdateJobStatus | None = None,
) -> tuple[UpdateManager, AsyncMock]:
    tracker = MagicMock()
    tracker.status = status or UpdateJobStatus()
    recorder = MagicMock()
    status_controller = MagicMock()
    runtime = SimpleNamespace(
        tracker=tracker,
        recorder=recorder,
        status_controller=status_controller,
        workflow=MagicMock(),
        startup_recovery=SimpleNamespace(recover=AsyncMock()),
        workflow_runner=SimpleNamespace(
            job_task=None,
            cancel=MagicMock(return_value=True),
            start=MagicMock(),
        ),
    )
    return UpdateManager(runtime=runtime), runtime.startup_recovery.recover


@pytest.mark.asyncio
async def test_workflow_stops_after_preparation_failure() -> None:
    workflow, prepare, plan, execute = _build_workflow()
    prepare.side_effect = UpdatePreparationError("validation failed")

    with pytest.raises(UpdatePreparationError, match="validation failed"):
        await workflow.run(context=UpdateWorkflowContext(), request=_wifi_request())

    prepare.assert_awaited_once()
    plan.assert_not_awaited()
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_workflow_carries_resolved_transport_session_through_context() -> None:
    workflow, prepare, plan, execute = _build_workflow()
    transport_session = AsyncMock()
    prepared = PreparedUpdateWorkflow(
        current_version="2026.4.3",
        transport_session=transport_session,
    )
    planned = object()
    prepare.return_value = prepared
    plan.return_value = planned
    context = UpdateWorkflowContext()

    await workflow.run(context=context, request=_wifi_request())

    prepare.assert_awaited_once()
    plan.assert_awaited_once_with(prepared)
    execute.assert_awaited_once_with(planned)
    assert context.transport_session is transport_session


@pytest.mark.asyncio
async def test_workflow_stops_after_release_failure() -> None:
    workflow, prepare, plan, execute = _build_workflow()
    transport_session = AsyncMock()
    prepare.return_value = PreparedUpdateWorkflow(
        current_version="2026.4.3",
        transport_session=transport_session,
    )
    plan.side_effect = UpdateReleaseError("release check failed")

    with pytest.raises(UpdateReleaseError, match="release check failed"):
        await workflow.run(context=UpdateWorkflowContext(), request=_wifi_request())

    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_recover_uses_persisted_transport_session() -> None:
    manager, recover = _build_manager(
        status=UpdateJobStatus(
            state=UpdateState.running,
            transport=UpdateTransport.usb_internet,
        ),
    )

    await manager.startup_recover()

    recover.assert_awaited_once()
