from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import MagicMock

import pytest

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError
from vibesensor.use_cases.updates.models import UpdateRequest, UpdateState, UpdateTransport
from vibesensor.use_cases.updates.workflow_runner import UpdateWorkflowRunner


def _wifi_request(ssid: str = "TestNet", password: str = "pass123") -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid=ssid,
        password=password,
    )


@pytest.mark.asyncio
async def test_start_rejects_concurrent_job() -> None:
    controller = MagicMock()
    recorder = MagicMock()
    runner = UpdateWorkflowRunner(
        status_controller=controller,
        status_recorder=recorder,
        timeout_s=10.0,
    )
    request = _wifi_request()
    started = asyncio.Event()
    release = asyncio.Event()

    async def running_workflow() -> None:
        started.set()
        await release.wait()

    runner.start(request=request, workflow=running_workflow)
    task = runner.job_task
    assert task is not None
    await asyncio.wait_for(started.wait(), timeout=1.0)

    with pytest.raises(UpdateError, match="already in progress"):
        runner.start(request=request, workflow=running_workflow)

    assert runner.cancel() is True
    with contextlib.suppress(asyncio.CancelledError):
        await task
    controller.start_job.assert_called_once_with(request)
    recorder.track_secret.assert_called_once_with(request.password)


@pytest.mark.asyncio
async def test_timeout_marks_failure_and_finishes_lifecycle() -> None:
    controller = MagicMock()
    recorder = MagicMock()
    runner = UpdateWorkflowRunner(
        status_controller=controller,
        status_recorder=recorder,
        timeout_s=0.01,
    )

    async def slow_workflow() -> None:
        await asyncio.sleep(1.0)

    runner.start(request=_wifi_request(), workflow=slow_workflow)
    task = runner.job_task
    assert task is not None
    await task

    recorder.add_issue.assert_any_call("timeout", "Update timed out after 0.01s")
    recorder.log.assert_any_call("Update timed out after 0.01s")
    controller.mark_failed.assert_called_once_with()
    recorder.clear_secrets.assert_called_once_with()
    controller.finish_cleanup.assert_called_once_with()


@pytest.mark.asyncio
async def test_update_error_marks_failure_without_propagating() -> None:
    controller = MagicMock()
    controller.status.state = UpdateState.running
    recorder = MagicMock()
    runner = UpdateWorkflowRunner(
        status_controller=controller,
        status_recorder=recorder,
        timeout_s=10.0,
    )

    async def broken_workflow() -> None:
        raise UpdateError("transport failed")

    runner.start(request=_wifi_request(), workflow=broken_workflow)
    task = runner.job_task
    assert task is not None
    await task

    recorder.add_issue.assert_any_call("workflow", "transport failed")
    controller.mark_failed.assert_called_once_with()
    recorder.clear_secrets.assert_called_once_with()
    controller.finish_cleanup.assert_called_once_with()


@pytest.mark.asyncio
async def test_cleanup_error_propagates_explicitly() -> None:
    controller = MagicMock()
    recorder = MagicMock()
    runner = UpdateWorkflowRunner(
        status_controller=controller,
        status_recorder=recorder,
        timeout_s=10.0,
    )

    async def broken_workflow() -> None:
        raise UpdateCleanupError("transport cleanup failed")

    runner.start(request=_wifi_request(), workflow=broken_workflow)
    task = runner.job_task
    assert task is not None

    with pytest.raises(UpdateCleanupError, match="transport cleanup failed"):
        await task

    recorder.clear_secrets.assert_called_once_with()
    controller.finish_cleanup.assert_called_once_with()
