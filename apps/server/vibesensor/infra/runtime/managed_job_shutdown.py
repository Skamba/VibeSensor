"""Managed-job shutdown helper for LifecycleManager.

Owns the collection and cancellation of managed jobs (update, flash)
previously inlined in ``LifecycleManager.stop()``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

LOGGER = logging.getLogger(__name__)


class ManagedJobSource(Protocol):
    @property
    def job_task(self) -> asyncio.Task[None] | None: ...


class ManagedJobShutdown:
    """Collect and cancel managed job tasks with a timeout."""

    __slots__ = ("_sources",)

    def __init__(self, sources: list[ManagedJobSource]) -> None:
        self._sources = sources

    async def cancel(self, *, timeout_s: float) -> list[asyncio.Task[None]]:
        """Cancel all active managed tasks and return any that did not finish."""
        tasks = [
            s.job_task for s in self._sources if s.job_task is not None and not s.job_task.done()
        ]
        return await _cancel_managed_tasks(tasks, timeout_s=timeout_s)


async def _cancel_managed_tasks(
    tasks: list[asyncio.Task[None]],
    *,
    timeout_s: float,
) -> list[asyncio.Task[None]]:
    """Cancel a list of tasks, returning those that did not finish."""
    for task in tasks:
        task.cancel()
    if not tasks:
        return []
    _done, _pending = await asyncio.wait(tasks, timeout=timeout_s)
    if _pending:
        LOGGER.warning(
            "%d managed shutdown task(s) did not finish within the cancellation "
            "deadline and remain pending: %s",
            len(_pending),
            [task.get_name() for task in _pending],
        )
    return [task for task in tasks if not task.done()]
