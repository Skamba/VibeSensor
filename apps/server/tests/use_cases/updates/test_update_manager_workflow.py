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
from vibesensor.use_cases.updates.workflow_runner import UpdateWorkflowContext


def _wifi_request(ssid: str = "TestNet", password: str = "pass123") -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid=ssid,
        password=password,
    )


def _build_manager(
    *,
    status: UpdateJobStatus | None = None,
) -> tuple[UpdateManager, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    tracker = MagicMock()
    tracker.status = status or UpdateJobStatus()
    preparation = MagicMock()
    preparation.prepare = AsyncMock()
    release_planner = MagicMock()
    release_planner.plan = AsyncMock()
    workflow_executor = MagicMock()
    workflow_executor.execute = AsyncMock()
    recovery_session = AsyncMock()
    runtime = SimpleNamespace(
        tracker=tracker,
        workflow_runner=SimpleNamespace(
            job_task=None,
            cancel=MagicMock(return_value=True),
            start=MagicMock(),
        ),
        build_run_runtime=lambda: SimpleNamespace(
            preparation=preparation,
            release_planner=release_planner,
            workflow_executor=workflow_executor,
        ),
        build_transport_sessions=lambda: SimpleNamespace(
            for_transport=lambda _transport: recovery_session,
        ),
    )
    return (
        UpdateManager(runtime=runtime),
        preparation.prepare,
        release_planner.plan,
        workflow_executor.execute,
        recovery_session.recover_interrupted_update,
    )


@pytest.mark.asyncio
async def test_run_update_stops_after_preparation_failure() -> None:
    manager, prepare, plan, execute, _recover = _build_manager()
    prepare.side_effect = UpdatePreparationError("validation failed")

    with pytest.raises(UpdatePreparationError, match="validation failed"):
        await manager._run_update(UpdateWorkflowContext(), _wifi_request())

    prepare.assert_awaited_once()
    plan.assert_not_awaited()
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_update_carries_resolved_transport_session_through_cleanup() -> None:
    manager, prepare, plan, execute, _recover = _build_manager()
    transport_session = AsyncMock()
    prepared = PreparedUpdateWorkflow(
        current_version="2026.4.3",
        transport_session=transport_session,
    )
    planned = object()
    prepare.return_value = prepared
    plan.return_value = planned
    context = UpdateWorkflowContext()

    await manager._run_update(context, _wifi_request())

    prepare.assert_awaited_once()
    plan.assert_awaited_once_with(prepared)
    execute.assert_awaited_once_with(planned)
    assert context.transport_session is transport_session


@pytest.mark.asyncio
async def test_run_update_cleans_up_prepared_session_after_release_failure() -> None:
    manager, prepare, plan, execute, _recover = _build_manager()
    transport_session = AsyncMock()
    prepared = PreparedUpdateWorkflow(
        current_version="2026.4.3",
        transport_session=transport_session,
    )
    prepare.return_value = prepared
    plan.side_effect = UpdateReleaseError("release check failed")

    with pytest.raises(UpdateReleaseError, match="release check failed"):
        await manager._run_update(UpdateWorkflowContext(), _wifi_request())

    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_recover_uses_persisted_transport_session() -> None:
    manager, _prepare, _plan, _execute, recover = _build_manager(
        status=UpdateJobStatus(
            state=UpdateState.running,
            transport=UpdateTransport.usb_internet,
        ),
    )

    await manager.startup_recover()

    recover.assert_awaited_once()
