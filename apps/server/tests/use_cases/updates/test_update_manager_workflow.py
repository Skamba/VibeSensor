from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.shared.exceptions import (
    UpdateCleanupError,
    UpdatePreparationError,
    UpdateReleaseError,
)
from vibesensor.use_cases.updates.manager import UpdateManager
from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdateRequest,
    UpdateState,
    UpdateTransport,
)
from vibesensor.use_cases.updates.run_models import PreparedUpdateRun
from vibesensor.use_cases.updates.workflow import UpdateWorkflow


def _wifi_request(ssid: str = "TestNet", password: str = "pass123") -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid=ssid,
        password=password,
    )


def _build_workflow() -> tuple[
    UpdateWorkflow,
    AsyncMock,
    AsyncMock,
    AsyncMock,
    AsyncMock,
    AsyncMock,
]:
    preparation = MagicMock()
    preparation.prepare = AsyncMock()
    release_planner = MagicMock()
    release_planner.plan = AsyncMock()
    workflow_executor = MagicMock()
    workflow_executor.execute = AsyncMock()
    transport_coordinator = MagicMock()
    transport_coordinator.cleanup_after_update = AsyncMock()
    runtime_details_refresher = MagicMock()
    runtime_details_refresher.refresh = AsyncMock()
    return (
        UpdateWorkflow(
            preparation=preparation,
            release_planner=release_planner,
            workflow_executor=workflow_executor,
            transport_coordinator=transport_coordinator,
            runtime_details_refresher=runtime_details_refresher,
        ),
        preparation.prepare,
        release_planner.plan,
        workflow_executor.execute,
        transport_coordinator.cleanup_after_update,
        runtime_details_refresher.refresh,
    )


def _build_manager(
    *,
    status: UpdateJobStatus | None = None,
) -> tuple[UpdateManager, AsyncMock]:
    tracker = MagicMock()
    tracker.status = status or UpdateJobStatus()
    runtime = SimpleNamespace(
        recover=AsyncMock(),
    )
    return (
        UpdateManager(
            status=tracker,
            workflow=MagicMock(),
            startup_recovery=runtime,
            usb_status_service=MagicMock(),
            timeout_s=10.0,
        ),
        runtime.recover,
    )


@pytest.mark.asyncio
async def test_workflow_stops_after_preparation_failure_and_finalizes_without_transport() -> None:
    workflow, prepare, plan, execute, cleanup, refresh = _build_workflow()
    prepare.side_effect = UpdatePreparationError("validation failed")

    with pytest.raises(UpdatePreparationError, match="validation failed"):
        await workflow.run(request=_wifi_request())

    prepare.assert_awaited_once()
    plan.assert_not_awaited()
    execute.assert_not_awaited()
    cleanup.assert_awaited_once_with(None)
    refresh.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_workflow_finalizes_the_prepared_transport_handle() -> None:
    workflow, prepare, plan, execute, cleanup, refresh = _build_workflow()
    prepared_transport = AsyncMock()
    prepared = PreparedUpdateRun(
        current_version="2026.4.3",
        prepared_transport=prepared_transport,
    )
    planned = object()
    prepare.return_value = prepared
    plan.return_value = planned

    await workflow.run(request=_wifi_request())

    prepare.assert_awaited_once()
    plan.assert_awaited_once_with(prepared)
    execute.assert_awaited_once_with(planned)
    cleanup.assert_awaited_once_with(prepared_transport)
    refresh.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_workflow_stops_after_release_failure_and_finalizes_prepared_transport() -> None:
    workflow, prepare, plan, execute, cleanup, refresh = _build_workflow()
    prepared_transport = AsyncMock()
    prepare.return_value = PreparedUpdateRun(
        current_version="2026.4.3",
        prepared_transport=prepared_transport,
    )
    plan.side_effect = UpdateReleaseError("release check failed")

    with pytest.raises(UpdateReleaseError, match="release check failed"):
        await workflow.run(request=_wifi_request())

    execute.assert_not_awaited()
    cleanup.assert_awaited_once_with(prepared_transport)
    refresh.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_workflow_adds_cleanup_note_to_workflow_bug() -> None:
    workflow, prepare, plan, execute, cleanup, refresh = _build_workflow()
    prepared_transport = AsyncMock()
    prepare.return_value = PreparedUpdateRun(
        current_version="2026.4.3",
        prepared_transport=prepared_transport,
    )
    plan.return_value = object()
    execute.side_effect = RuntimeError("workflow bug")
    cleanup.side_effect = UpdateCleanupError("transport cleanup failed")

    with pytest.raises(RuntimeError, match="workflow bug") as exc_info:
        await workflow.run(request=_wifi_request())

    assert exc_info.value.__notes__ == ["Cleanup also failed: transport cleanup failed"]
    refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_recover_uses_persisted_transport() -> None:
    manager, recover = _build_manager(
        status=UpdateJobStatus(
            state=UpdateState.running,
            transport=UpdateTransport.usb_internet,
        ),
    )

    await manager.startup_recover()

    recover.assert_awaited_once()
