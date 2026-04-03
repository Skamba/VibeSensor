"""Canonical task/lifecycle boundary for one updater workflow run."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError
from vibesensor.use_cases.updates.cleanup import UpdateCleanupCoordinator
from vibesensor.use_cases.updates.models import UpdateRequest
from vibesensor.use_cases.updates.status import UpdateStatusTracker

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSession

__all__ = ["UpdateWorkflowContext", "UpdateWorkflowRunner"]

ManagedUpdateWorkflow = Callable[["UpdateWorkflowContext"], Awaitable[None]]


@dataclass(slots=True)
class UpdateWorkflowContext:
    """Mutable run-scoped workflow state shared with cleanup sequencing."""

    transport_session: UpdateTransportSession | None = None


class UpdateWorkflowRunner:
    """Own update task creation, timeout/cancel handling, and cleanup sequencing."""

    __slots__ = ("_cleanup", "_task", "_task_name", "_timeout_s", "_tracker")

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        cleanup: UpdateCleanupCoordinator,
        timeout_s: float,
        task_name: str = "system-update",
    ) -> None:
        self._tracker = tracker
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
        self._tracker.start_job(request)
        self._tracker.track_secret(request.password)
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
        except UpdateError:
            return
        except TimeoutError:
            self._tracker.fail("timeout", f"Update timed out after {self._timeout_s}s")
            self._tracker.log(f"Update timed out after {self._timeout_s}s")
        except asyncio.CancelledError:
            self._tracker.fail("cancelled", "Update was cancelled")
            self._tracker.log("Update cancelled")
            raise
        finally:
            await self._cleanup_after_workflow(context.transport_session)

    async def _cleanup_after_workflow(
        self,
        transport_session: UpdateTransportSession | None,
    ) -> None:
        active_error = sys.exc_info()[1]
        try:
            await self._cleanup.run(transport_session)
        except asyncio.CancelledError:
            raise
        except UpdateCleanupError as exc:
            if active_error is None:
                raise
            if isinstance(active_error, asyncio.CancelledError):
                raise UpdateCleanupError(f"Cleanup failed after cancellation: {exc}") from exc
            active_error.add_note(f"Cleanup also failed: {exc}")
        finally:
            self._tracker.clear_secrets()
            self._tracker.finish_cleanup()
