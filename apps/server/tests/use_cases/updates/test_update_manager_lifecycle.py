from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from test_support.tracing import configured_trace_output, read_trace_output

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError
from vibesensor.use_cases.updates.manager import UpdateManager
from vibesensor.use_cases.updates.models import (
    UpdatePhase,
    UpdateRequest,
    UpdateState,
    UpdateTransport,
)
from vibesensor.use_cases.updates.status import (
    UpdateStateStore,
    UpdateTerminalStateReporter,
    build_update_status_tracker,
)


def _wifi_request(ssid: str = "TestNet", password: str = "pass123") -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid=ssid,
        password=password,
    )


def _build_manager(
    tmp_path: Path,
    *,
    timeout_s: float = 10.0,
) -> tuple[UpdateManager, UpdateStateStore, object, AsyncMock]:
    state_store = UpdateStateStore(tmp_path / "update_status.json")
    tracker = build_update_status_tracker(state_store=state_store)
    reporter = UpdateTerminalStateReporter(status=tracker)
    workflow_run = AsyncMock()
    manager = UpdateManager(
        status=tracker,
        reporter=reporter,
        workflow=SimpleNamespace(run=workflow_run),
        startup_recovery=SimpleNamespace(recover=AsyncMock()),
        usb_status_service=MagicMock(),
        timeout_s=timeout_s,
    )
    return manager, state_store, tracker, workflow_run


def _load_status(state_store: UpdateStateStore):
    status = state_store.load()
    assert status is not None
    return status


def _assert_secret_not_persisted(state_store: UpdateStateStore, secret: str) -> None:
    assert secret not in state_store.path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_start_rejects_concurrent_job_and_keeps_secret_redacted(
    tmp_path: Path,
) -> None:
    manager, state_store, _tracker, workflow_run = _build_manager(tmp_path)
    request = _wifi_request()
    started = asyncio.Event()
    release = asyncio.Event()

    async def running_workflow(*, request: UpdateRequest) -> None:
        assert request == _wifi_request()
        started.set()
        await release.wait()

    workflow_run.side_effect = running_workflow
    manager.start(request.ssid, request.password, transport=request.transport)
    task = manager.job_task
    assert task is not None
    await asyncio.wait_for(started.wait(), timeout=1.0)

    running_status = _load_status(state_store)
    assert running_status.state == UpdateState.running
    _assert_secret_not_persisted(state_store, request.password)

    with pytest.raises(UpdateError, match="already in progress"):
        manager.start(request.ssid, request.password, transport=request.transport)

    assert manager.cancel() is True
    with contextlib.suppress(asyncio.CancelledError):
        await task

    final_status = _load_status(state_store)
    assert final_status.state == UpdateState.failed
    assert final_status.finished_at is not None
    assert any(issue.message == "Update was cancelled" for issue in final_status.issues)
    _assert_secret_not_persisted(state_store, request.password)


@pytest.mark.asyncio
async def test_timeout_marks_failure_and_persists_cleanup_state(tmp_path: Path) -> None:
    async def slow_workflow(*, request: UpdateRequest) -> None:
        assert request == _wifi_request()
        await asyncio.sleep(1.0)

    manager, state_store, _tracker, workflow_run = _build_manager(tmp_path, timeout_s=0.01)
    workflow_run.side_effect = slow_workflow
    request = _wifi_request()
    manager.start(request.ssid, request.password, transport=request.transport)
    task = manager.job_task
    assert task is not None
    await task

    status = _load_status(state_store)
    assert status.state == UpdateState.failed
    assert status.finished_at is not None
    assert any(issue.message == "Update timed out after 0.01s" for issue in status.issues)
    _assert_secret_not_persisted(state_store, request.password)


@pytest.mark.asyncio
async def test_update_error_marks_failure_without_propagating(tmp_path: Path) -> None:
    manager, state_store, _tracker, workflow_run = _build_manager(tmp_path)
    error = UpdateError("transport failed")
    workflow_run.side_effect = error
    request = _wifi_request()
    manager.start(request.ssid, request.password, transport=request.transport)
    task = manager.job_task
    assert task is not None
    await task

    status = _load_status(state_store)
    assert status.state == UpdateState.failed
    assert status.finished_at is not None
    assert any(issue.message == "transport failed" for issue in status.issues)
    _assert_secret_not_persisted(state_store, request.password)


@pytest.mark.asyncio
async def test_cleanup_error_propagates_explicitly_and_persists_failure(tmp_path: Path) -> None:
    manager, state_store, _tracker, workflow_run = _build_manager(tmp_path)
    error = UpdateCleanupError("transport cleanup failed")
    workflow_run.side_effect = error
    request = _wifi_request()
    manager.start(request.ssid, request.password, transport=request.transport)
    task = manager.job_task
    assert task is not None

    with pytest.raises(UpdateCleanupError, match="transport cleanup failed"):
        await task

    status = _load_status(state_store)
    assert status.state == UpdateState.failed
    assert status.finished_at is not None
    assert any(issue.message == "transport cleanup failed" for issue in status.issues)
    _assert_secret_not_persisted(state_store, request.password)


@pytest.mark.asyncio
async def test_start_exports_update_workflow_trace_span(tmp_path: Path) -> None:
    manager, state_store, tracker, workflow_run = _build_manager(tmp_path)
    request = _wifi_request()

    async def successful_workflow(*, request: UpdateRequest) -> None:
        assert request == _wifi_request()
        tracker.transition(UpdatePhase.connecting_usb_internet)
        tracker.transition(UpdatePhase.checking)
        tracker.mark_success("Update completed")

    workflow_run.side_effect = successful_workflow

    with configured_trace_output(tmp_path) as trace_path:
        manager.start(request.ssid, request.password, transport=request.transport)
        task = manager.job_task
        assert task is not None
        await task

    status = _load_status(state_store)
    assert status.state == UpdateState.success
    assert status.finished_at is not None
    _assert_secret_not_persisted(state_store, request.password)
    span = next(item for item in read_trace_output(trace_path) if item["name"] == "update.workflow")
    assert span["attributes"]["vibesensor.transport"] == "wifi"
    assert span["attributes"]["vibesensor.final_state"] == "success"
