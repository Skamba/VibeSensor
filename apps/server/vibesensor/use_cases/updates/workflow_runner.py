"""Canonical task/lifecycle boundary for one updater workflow run."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError
from vibesensor.use_cases.updates.models import UpdateRequest, UpdateState
from vibesensor.use_cases.updates.status import UpdateStatusController, UpdateStatusRecorder

__all__ = ["UpdateWorkflowRunner"]

ManagedUpdateWorkflow = Callable[[], Awaitable[None]]


class UpdateWorkflowRunner:
    """Own update task creation, timeout handling, and cancellation lifecycle."""

    __slots__ = (
        "_status_controller",
        "_status_recorder",
        "_task",
        "_task_name",
        "_timeout_s",
    )

    def __init__(
        self,
        *,
        status_controller: UpdateStatusController,
        status_recorder: UpdateStatusRecorder,
        timeout_s: float,
        task_name: str = "system-update",
    ) -> None:
        self._status_controller = status_controller
        self._status_recorder = status_recorder
        self._timeout_s = timeout_s
        self._task_name = task_name
        self._task: asyncio.Task[None] | None = None

    @property
    def job_task(self) -> asyncio.Task[None] | None:
        return self._task

    def start(
        self,
        *,
        request: UpdateRequest,
        workflow: ManagedUpdateWorkflow,
    ) -> None:
        if self._task is not None and not self._task.done():
            raise UpdateError("Update already in progress", status="conflict")
        self._status_controller.start_job(request)
        self._status_recorder.track_secret(request.password)
        self._task = asyncio.get_running_loop().create_task(
            self._run_managed_workflow(workflow=workflow),
            name=self._task_name,
        )

    def cancel(self) -> bool:
        if self._task is None or self._task.done():
            return False
        self._task.cancel()
        return True

    async def _run_managed_workflow(
        self,
        *,
        workflow: ManagedUpdateWorkflow,
    ) -> None:
        try:
            await asyncio.wait_for(workflow(), timeout=self._timeout_s)
        except UpdateCleanupError:
            raise
        except UpdateError as exc:
            if self._status_controller.status.state is UpdateState.running:
                self._status_recorder.add_issue("workflow", str(exc))
                self._status_controller.mark_failed()
            return
        except TimeoutError:
            self._status_recorder.add_issue(
                "timeout",
                f"Update timed out after {self._timeout_s}s",
            )
            self._status_controller.mark_failed()
            self._status_recorder.log(f"Update timed out after {self._timeout_s}s")
        except asyncio.CancelledError:
            self._status_recorder.add_issue("cancelled", "Update was cancelled")
            self._status_controller.mark_failed()
            self._status_recorder.log("Update cancelled")
            raise
        finally:
            self._status_recorder.clear_secrets()
            self._status_controller.finish_cleanup()
