"""Interrupted-update recovery collaborator.

Owns the interrupted-job check, cleanup call, and persistence step that
``UpdateManager.startup_recover()`` delegates to.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from vibesensor.use_cases.updates.models import UpdateState
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSessions

TransportSessionsFactory = Callable[[], UpdateTransportSessions]

LOGGER = logging.getLogger(__name__)


class InterruptedUpdateRecovery:
    """Detect and recover from an update job interrupted by a server restart."""

    __slots__ = ("_tracker", "_transport_sessions_factory")

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        transport_sessions_factory: TransportSessionsFactory,
    ) -> None:
        self._tracker = tracker
        self._transport_sessions_factory = transport_sessions_factory

    def needs_recovery(self) -> bool:
        """Return True when the persisted status indicates an interrupted job."""
        status = self._tracker.status
        return status.state == UpdateState.running and status.finished_at is None

    async def recover(self) -> None:
        """Mark the interrupted job as failed, run transport cleanup, and persist."""
        LOGGER.warning("Detected interrupted update job; marking as failed and cleaning up")
        self._tracker.mark_interrupted("Update interrupted by server restart")
        transport_session = self._transport_sessions_factory().for_transport(
            self._tracker.status.transport,
        )
        await transport_session.recover_interrupted_update()
        self._tracker.persist()
