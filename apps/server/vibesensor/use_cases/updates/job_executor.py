from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable, Coroutine

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError

BeforeStartCallback = Callable[[], None]
CleanupCallback = Callable[[], Awaitable[None]]
VoidCallback = Callable[[], None]
WorkflowFactory = Callable[[], Awaitable[object]]
TaskCoroutineFactory = Callable[[], Coroutine[object, object, None]]


class UpdateJobExecutor:
    """Own update task lifecycle mechanics apart from the update workflow itself."""

    __slots__ = ("_task", "_task_name")

    def __init__(self, *, task_name: str = "system-update") -> None:
        self._task_name = task_name
        self._task: asyncio.Task[None] | None = None

    @property
    def job_task(self) -> asyncio.Task[None] | None:
        return self._task

    def start(
        self,
        workflow_factory: TaskCoroutineFactory,
        *,
        before_start: BeforeStartCallback | None = None,
    ) -> None:
        """Start a new update task after running any synchronous pre-start hook."""
        if self._task is not None and not self._task.done():
            raise UpdateError("Update already in progress", status="conflict")
        if before_start is not None:
            before_start()
        self._task = asyncio.get_running_loop().create_task(
            workflow_factory(),
            name=self._task_name,
        )

    def cancel(self) -> bool:
        """Request cancellation for the active task."""
        if self._task is None or self._task.done():
            return False
        self._task.cancel()
        return True

    async def run(
        self,
        *,
        workflow_factory: WorkflowFactory,
        timeout_s: float,
        on_timeout: VoidCallback,
        on_cancelled: VoidCallback,
        cleanup: CleanupCallback,
    ) -> None:
        """Run the workflow with timeout/cancel handling and guaranteed cleanup."""
        try:
            await asyncio.wait_for(workflow_factory(), timeout=timeout_s)
        except TimeoutError:
            on_timeout()
        except asyncio.CancelledError:
            on_cancelled()
            raise
        finally:
            await self._cleanup_after_workflow(cleanup)

    async def _cleanup_after_workflow(self, cleanup: CleanupCallback) -> None:
        active_error = sys.exc_info()[1]
        if active_error is None:
            try:
                await cleanup()
            except asyncio.CancelledError:
                raise
            except (OSError, UpdateError) as exc:
                raise UpdateCleanupError(f"Cleanup failed: {exc}") from exc
            return

        try:
            await cleanup()
        except asyncio.CancelledError:
            raise
        except (OSError, UpdateError) as exc:
            if isinstance(active_error, asyncio.CancelledError):
                raise UpdateCleanupError(f"Cleanup failed after cancellation: {exc}") from exc
            active_error.add_note(f"Cleanup also failed: {exc}")
        except Exception as exc:
            if isinstance(active_error, asyncio.CancelledError):
                raise
            active_error.add_note(f"Cleanup also failed: {exc}")
