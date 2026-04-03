from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine

from vibesensor.shared.exceptions import UpdateError

BeforeStartCallback = Callable[[], None]
CleanupCallback = Callable[[], Awaitable[None]]
UnexpectedCallback = Callable[[Exception], None]
CleanupErrorCallback = Callable[[Exception], None]
VoidCallback = Callable[[], None]
WorkflowFactory = Callable[[], Awaitable[None]]
TaskCoroutineFactory = Callable[[], Coroutine[object, object, None]]


class UpdateJobExecutor:
    """Own update task lifecycle mechanics apart from the update workflow itself."""

    __slots__ = ("_cancel_event", "_task", "_task_name")

    def __init__(self, *, task_name: str = "system-update") -> None:
        self._task_name = task_name
        self._task: asyncio.Task[None] | None = None
        self._cancel_event = asyncio.Event()

    @property
    def job_task(self) -> asyncio.Task[None] | None:
        return self._task

    def cancel_requested(self) -> bool:
        """Return whether cancellation has been requested for the active job."""
        return self._cancel_event.is_set()

    def start(
        self,
        workflow_factory: TaskCoroutineFactory,
        *,
        before_start: BeforeStartCallback | None = None,
    ) -> None:
        """Start a new update task after running any synchronous pre-start hook."""
        if self._task is not None and not self._task.done():
            raise UpdateError("Update already in progress", status="conflict")
        self._cancel_event.clear()
        if before_start is not None:
            before_start()
        self._task = asyncio.get_running_loop().create_task(
            workflow_factory(),
            name=self._task_name,
        )

    def cancel(self) -> bool:
        """Request cancellation for the active task and signal the cancel event."""
        if self._task is None or self._task.done():
            return False
        self._cancel_event.set()
        self._task.cancel()
        return True

    async def run(
        self,
        *,
        workflow_factory: WorkflowFactory,
        timeout_s: float,
        on_timeout: VoidCallback,
        on_cancelled: VoidCallback,
        on_unexpected: UnexpectedCallback,
        cleanup: CleanupCallback,
        on_cleanup_error: CleanupErrorCallback,
    ) -> None:
        """Run the workflow with timeout/cancel handling and guaranteed cleanup."""
        primary_error: BaseException | None = None
        cancelled = False
        try:
            await asyncio.wait_for(workflow_factory(), timeout=timeout_s)
        except TimeoutError:
            on_timeout()
        except asyncio.CancelledError as exc:
            cancelled = True
            on_cancelled()
            primary_error = exc
        except Exception as exc:
            on_unexpected(exc)
            primary_error = exc

        cleanup_error: Exception | None = None
        try:
            await cleanup()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            on_cleanup_error(exc)
            cleanup_error = exc

        if cancelled and cleanup_error is not None:
            raise cleanup_error
        if primary_error is not None:
            raise primary_error
        if cleanup_error is not None:
            raise cleanup_error
