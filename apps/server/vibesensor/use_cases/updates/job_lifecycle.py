from __future__ import annotations

from vibesensor.use_cases.updates.cleanup import UpdateCleanupCoordinator
from vibesensor.use_cases.updates.models import UpdateRequest
from vibesensor.use_cases.updates.status import UpdateStatusTracker


class UpdateJobLifecycleHandler:
    """Own stateful update job lifecycle callbacks and cleanup sequencing."""

    __slots__ = ("_cleanup", "_tracker")

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        cleanup: UpdateCleanupCoordinator,
    ) -> None:
        self._tracker = tracker
        self._cleanup = cleanup

    def prepare_start(self, request: UpdateRequest) -> None:
        self._tracker.start_job(request)
        self._tracker.track_secret(request.password)

    def handle_timeout(self, timeout_s: float) -> None:
        self._tracker.fail("timeout", f"Update timed out after {timeout_s}s")
        self._tracker.log(f"Update timed out after {timeout_s}s")

    def handle_cancelled(self) -> None:
        self._tracker.fail("cancelled", "Update was cancelled")
        self._tracker.log("Update cancelled")

    async def cleanup_after_update(self) -> None:
        try:
            await self._cleanup.run()
        finally:
            self._tracker.clear_secrets()
            self._tracker.finish_cleanup()
