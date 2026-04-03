from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from vibesensor.use_cases.updates.models import UpdateRequest
from vibesensor.use_cases.updates.status import UpdateStatusTracker, collect_runtime_details
from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSessions

TransportSessionsFactory = Callable[[], UpdateTransportSessions]


class UpdateJobLifecycleHandler:
    """Own stateful update job lifecycle callbacks and cleanup sequencing."""

    __slots__ = ("_logger", "_repo", "_tracker", "_transport_sessions_factory")

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        repo: Path,
        transport_sessions_factory: TransportSessionsFactory,
        logger: logging.Logger,
    ) -> None:
        self._tracker = tracker
        self._repo = repo
        self._transport_sessions_factory = transport_sessions_factory
        self._logger = logger

    def prepare_start(self, request: UpdateRequest) -> None:
        self._tracker.start_job(request)
        self._tracker.track_secret(request.password)

    def handle_timeout(self, timeout_s: float) -> None:
        self._tracker.fail("timeout", f"Update timed out after {timeout_s}s")
        self._tracker.log(f"Update timed out after {timeout_s}s")

    def handle_cancelled(self) -> None:
        self._tracker.fail("cancelled", "Update was cancelled")
        self._tracker.log("Update cancelled")

    def handle_unexpected(self, exc: Exception) -> None:
        self._tracker.fail("unexpected", f"Unexpected error: {exc}")
        self._logger.exception("update: unexpected error")

    def handle_cleanup_error(self, exc: Exception) -> None:
        self._tracker.fail("cleanup", f"Cleanup failed: {exc}")
        self._logger.exception("update: cleanup error")

    async def cleanup_after_update(self) -> None:
        tracker = self._tracker
        transport_session = self._transport_sessions_factory().for_transport(
            tracker.status.transport,
        )
        try:
            await transport_session.cleanup_after_update()
            tracker.set_runtime(await asyncio.to_thread(collect_runtime_details, self._repo))
        finally:
            tracker.clear_secrets()
            tracker.finish_cleanup()
