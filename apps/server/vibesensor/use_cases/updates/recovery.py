"""Interrupted-update recovery collaborator.

Owns the interrupted-job check, cleanup call, and persistence step that
``UpdateManager.startup_recover()`` delegates to.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from vibesensor.use_cases.updates.models import UpdateState
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wifi import UpdateWifiOrchestrator

WifiFactory = Callable[[], UpdateWifiOrchestrator]

LOGGER = logging.getLogger(__name__)


class InterruptedUpdateRecovery:
    """Detect and recover from an update job interrupted by a server restart."""

    __slots__ = ("_tracker", "_wifi_factory")

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        wifi_factory: WifiFactory,
    ) -> None:
        self._tracker = tracker
        self._wifi_factory = wifi_factory

    def needs_recovery(self) -> bool:
        """Return True when the persisted status indicates an interrupted job."""
        status = self._tracker.status
        return status.state == UpdateState.running and status.finished_at is None

    async def recover(self) -> None:
        """Mark the interrupted job as failed, run Wi-Fi cleanup, and persist."""
        LOGGER.warning("Detected interrupted update job; marking as failed and cleaning up")
        self._tracker.mark_interrupted("Update interrupted by server restart")
        wifi = self._wifi_factory()
        await wifi.recover_interrupted_update()
        self._tracker.persist()
