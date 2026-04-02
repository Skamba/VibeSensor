from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from vibesensor.use_cases.updates.models import UpdateRequest
from vibesensor.use_cases.updates.status import UpdateStatusTracker, collect_runtime_details
from vibesensor.use_cases.updates.wifi import UpdateWifiOrchestrator

WifiFactory = Callable[[], UpdateWifiOrchestrator]


class UpdateJobLifecycleHandler:
    """Own stateful update job lifecycle callbacks and cleanup sequencing."""

    __slots__ = ("_logger", "_repo", "_tracker", "_wifi_factory")

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        repo: Path,
        wifi_factory: WifiFactory,
        logger: logging.Logger,
    ) -> None:
        self._tracker = tracker
        self._repo = repo
        self._wifi_factory = wifi_factory
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

    def handle_cancelled_cleanup_error(self, exc: Exception) -> None:
        self._logger.warning(
            "Update cleanup interrupted during cancellation",
            exc_info=(type(exc), exc, exc.__traceback__),
        )

    async def cleanup_after_update(self) -> None:
        tracker = self._tracker
        wifi = self._wifi_factory()
        try:
            await wifi.maybe_restore_hotspot_during_cleanup()
            tracker.set_runtime(await asyncio.to_thread(collect_runtime_details, self._repo))
            tracker.extend_issues(await wifi.collect_cleanup_diagnostics())
        finally:
            tracker.clear_secrets()
            tracker.finish_cleanup()
