from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.shared.exceptions import UpdatePreparationError, UpdateReleaseError
from vibesensor.use_cases.updates.job_executor import UpdateJobExecutor
from vibesensor.use_cases.updates.manager import UpdateManager
from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdateRequest,
    UpdateState,
    UpdateTransport,
)
from vibesensor.use_cases.updates.preparation import PreparedUpdateWorkflow


def _wifi_request(ssid: str = "TestNet", password: str = "pass123") -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid=ssid,
        password=password,
    )


def _build_manager(
    *,
    status: UpdateJobStatus | None = None,
) -> tuple[UpdateManager, AsyncMock, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    tracker = MagicMock()
    tracker.status = status or UpdateJobStatus()
    lifecycle = MagicMock(
        handle_timeout=MagicMock(),
        handle_cancelled=MagicMock(),
        cleanup_after_update=AsyncMock(return_value=None),
    )
    preparation = MagicMock()
    preparation.prepare = AsyncMock()
    release_planner = MagicMock()
    release_planner.plan = AsyncMock()
    workflow_executor = MagicMock()
    workflow_executor.execute = AsyncMock()
    recovery_session = AsyncMock()
    runtime = SimpleNamespace(
        tracker=tracker,
        executor=UpdateJobExecutor(task_name="system-update"),
        lifecycle=lifecycle,
        build_run_runtime=lambda: SimpleNamespace(
            preparation=preparation,
            release_planner=release_planner,
            workflow_executor=workflow_executor,
        ),
        build_transport_sessions=lambda *_args, **_kwargs: SimpleNamespace(
            for_transport=lambda _transport: recovery_session,
        ),
    )
    return (
        UpdateManager(runtime=runtime),
        preparation.prepare,
        release_planner.plan,
        workflow_executor.execute,
        lifecycle.cleanup_after_update,
        recovery_session.recover_interrupted_update,
    )


@pytest.mark.asyncio
async def test_run_update_stops_after_preparation_failure() -> None:
    manager, prepare, plan, execute, cleanup, _recover = _build_manager()
    prepare.side_effect = UpdatePreparationError("validation failed")

    await manager._run_update(_wifi_request())

    prepare.assert_awaited_once()
    plan.assert_not_awaited()
    execute.assert_not_awaited()
    cleanup.assert_awaited_once_with(None)


@pytest.mark.asyncio
async def test_run_update_carries_resolved_transport_session_through_cleanup() -> None:
    manager, prepare, plan, execute, cleanup, _recover = _build_manager()
    transport_session = AsyncMock()
    prepared = PreparedUpdateWorkflow(
        current_version="2026.4.3",
        transport_session=transport_session,
    )
    planned = object()
    prepare.return_value = prepared
    plan.return_value = planned

    await manager._run_update(_wifi_request())

    prepare.assert_awaited_once()
    plan.assert_awaited_once_with(prepared)
    execute.assert_awaited_once_with(planned)
    cleanup.assert_awaited_once_with(transport_session)


@pytest.mark.asyncio
async def test_run_update_cleans_up_prepared_session_after_release_failure() -> None:
    manager, prepare, plan, execute, cleanup, _recover = _build_manager()
    transport_session = AsyncMock()
    prepared = PreparedUpdateWorkflow(
        current_version="2026.4.3",
        transport_session=transport_session,
    )
    prepare.return_value = prepared
    plan.side_effect = UpdateReleaseError("release check failed")

    await manager._run_update(_wifi_request())

    execute.assert_not_awaited()
    cleanup.assert_awaited_once_with(transport_session)


@pytest.mark.asyncio
async def test_startup_recover_uses_persisted_transport_session() -> None:
    manager, _prepare, _plan, _execute, _cleanup, recover = _build_manager(
        status=UpdateJobStatus(
            state=UpdateState.running,
            transport=UpdateTransport.usb_internet,
        ),
    )

    await manager.startup_recover()

    recover.assert_awaited_once()
