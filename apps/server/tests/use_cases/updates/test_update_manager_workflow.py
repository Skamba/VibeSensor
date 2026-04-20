from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from test_support.tracing import configured_trace_output, read_trace_output

from vibesensor.shared.exceptions import (
    UpdatePreparationError,
    UpdateReleaseError,
)
from vibesensor.use_cases.updates.finalization import UpdateWorkflowFinalizer
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
]:
    preparation = MagicMock()
    preparation.prepare = AsyncMock()
    release_planner = MagicMock()
    release_planner.plan = AsyncMock()
    workflow_executor = MagicMock()
    workflow_executor.execute = AsyncMock()
    finalizer = MagicMock(spec=UpdateWorkflowFinalizer)
    finalizer.finalize = AsyncMock()
    return (
        UpdateWorkflow(
            preparation=preparation,
            release_planner=release_planner,
            workflow_executor=workflow_executor,
            finalizer=finalizer,
        ),
        preparation.prepare,
        release_planner.plan,
        workflow_executor.execute,
        finalizer.finalize,
    )


def _build_manager(
    *,
    status: UpdateJobStatus | None = None,
) -> tuple[UpdateManager, AsyncMock]:
    tracker = MagicMock()
    tracker.status = status or UpdateJobStatus()
    reporter = MagicMock()
    runtime = SimpleNamespace(
        recover=AsyncMock(),
    )
    return (
        UpdateManager(
            status=tracker,
            reporter=reporter,
            workflow=MagicMock(),
            startup_recovery=runtime,
            usb_status_service=MagicMock(),
            timeout_s=10.0,
        ),
        runtime.recover,
    )


@pytest.mark.asyncio
async def test_workflow_stops_after_preparation_failure_and_finalizes_without_transport() -> None:
    workflow, prepare, plan, execute, finalize = _build_workflow()
    prepare.side_effect = UpdatePreparationError("validation failed")

    with pytest.raises(UpdatePreparationError, match="validation failed"):
        await workflow.run(request=_wifi_request())

    prepare.assert_awaited_once()
    plan.assert_not_awaited()
    execute.assert_not_awaited()
    finalize.assert_awaited_once()
    assert finalize.await_args.args == (None,)
    assert isinstance(finalize.await_args.kwargs["prior_error"], UpdatePreparationError)


@pytest.mark.asyncio
async def test_workflow_finalizes_the_prepared_transport_handle() -> None:
    workflow, prepare, plan, execute, finalize = _build_workflow()
    prepared_transport = AsyncMock()
    prepared = PreparedUpdateRun(
        prepared_transport=prepared_transport,
    )
    planned = object()
    prepare.return_value = prepared
    plan.return_value = planned

    await workflow.run(request=_wifi_request())

    prepare.assert_awaited_once()
    plan.assert_awaited_once_with(prepared)
    execute.assert_awaited_once_with(planned)
    finalize.assert_awaited_once_with(prepared_transport, prior_error=None)


@pytest.mark.asyncio
async def test_workflow_stops_after_release_failure_and_finalizes_prepared_transport() -> None:
    workflow, prepare, plan, execute, finalize = _build_workflow()
    prepared_transport = AsyncMock()
    prepare.return_value = PreparedUpdateRun(
        prepared_transport=prepared_transport,
    )
    plan.side_effect = UpdateReleaseError("release check failed")

    with pytest.raises(UpdateReleaseError, match="release check failed"):
        await workflow.run(request=_wifi_request())

    execute.assert_not_awaited()
    finalize.assert_awaited_once()
    assert finalize.await_args.args == (prepared_transport,)
    assert isinstance(finalize.await_args.kwargs["prior_error"], UpdateReleaseError)


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


@pytest.mark.asyncio
async def test_startup_recover_exports_trace_span(tmp_path: Path) -> None:
    manager, recover = _build_manager()

    with configured_trace_output(tmp_path) as trace_path:
        await manager.startup_recover()

    recover.assert_awaited_once()
    span = next(
        item for item in read_trace_output(trace_path) if item["name"] == "update.startup_recover"
    )
    assert span["attributes"] == {}
