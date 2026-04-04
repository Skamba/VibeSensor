"""Canonical task/lifecycle boundary for one updater workflow run."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError
from vibesensor.use_cases.updates.cleanup import UpdateCleanupCoordinator
from vibesensor.use_cases.updates.models import UpdateRequest, UpdateState
from vibesensor.use_cases.updates.status import UpdateStatusController, UpdateStatusRecorder
from vibesensor.use_cases.updates.transport_coordinator import PreparedUpdateTransport

__all__ = ["UpdateWorkflowContext", "UpdateWorkflowRunner"]

ManagedUpdateWorkflow = Callable[["UpdateWorkflowContext"], Awaitable[None]]


@dataclass(slots=True)
class UpdateWorkflowContext:
    """Mutable run-scoped workflow state shared with cleanup sequencing."""

    transport: PreparedUpdateTransport | None = None


class UpdateWorkflowRunner:
    """Own update task creation, timeout/cancel handling, and cleanup sequencing."""

    __slots__ = (
        "_cleanup",
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
        cleanup: UpdateCleanupCoordinator,
        timeout_s: float,
        task_name: str = "system-update",
    ) -> None:
        self._status_controller = status_controller
        self._status_recorder = status_recorder
        self._cleanup = cleanup
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
        context = UpdateWorkflowContext()
        self._task = asyncio.get_running_loop().create_task(
            self._run_managed_workflow(
                context=context,
                workflow=workflow,
            ),
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
        context: UpdateWorkflowContext,
        workflow: ManagedUpdateWorkflow,
    ) -> None:
        try:
            await asyncio.wait_for(workflow(context), timeout=self._timeout_s)
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
            await self._cleanup_after_workflow(context.transport)

    async def _cleanup_after_workflow(
        self,
        transport: PreparedUpdateTransport | None,
    ) -> None:
        active_error = sys.exc_info()[1]
        try:
            await self._cleanup.run(transport)
        except asyncio.CancelledError:
            raise
        except UpdateCleanupError as exc:
            if active_error is None:
                raise
            if isinstance(active_error, asyncio.CancelledError):
                raise UpdateCleanupError(f"Cleanup failed after cancellation: {exc}") from exc
            active_error.add_note(f"Cleanup also failed: {exc}")
        finally:
            self._status_recorder.clear_secrets()
            self._status_controller.finish_cleanup()
