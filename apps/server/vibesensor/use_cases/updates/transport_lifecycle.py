"""Transport lifecycle boundary for update workflows."""

from __future__ import annotations

import sys
from collections.abc import Callable

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError, UpdateTransportError
from vibesensor.use_cases.updates.models import UpdateRequest, UpdateState
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport_sessions import (
    UpdateTransportSession,
    UpdateTransportSessions,
)

TransportSessionsFactory = Callable[[], UpdateTransportSessions]

__all__ = ["TransportSessionsFactory", "UpdateTransportLifecycle"]


class UpdateTransportLifecycle:
    """Own transport preparation, success finalization, cleanup, and recovery."""

    __slots__ = ("_sessions_factory", "_tracker")

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        sessions_factory: TransportSessionsFactory,
    ) -> None:
        self._tracker = tracker
        self._sessions_factory = sessions_factory

    def needs_recovery(self) -> bool:
        status = self._tracker.status
        return status.state == UpdateState.running and status.finished_at is None

    async def prepare(self, request: UpdateRequest) -> None:
        session = self._sessions_factory().for_request(request)
        try:
            await session.prepare(request)
        except UpdateTransportError:
            await self._abort_preparation(session)
            raise

    async def complete_success(self, *, message: str) -> None:
        await self._current_session().complete_success(message)

    async def cleanup_after_update(self) -> None:
        await self._current_session().cleanup_after_update()

    async def recover_interrupted_update(self) -> None:
        await self._current_session().recover_interrupted_update()

    def _current_session(self) -> UpdateTransportSession:
        return self._sessions_factory().for_transport(self._tracker.status.transport)

    async def _abort_preparation(self, session: UpdateTransportSession) -> None:
        active_error = sys.exc_info()[1]
        try:
            await session.abort_preparation()
        except (OSError, UpdateError) as exc:
            if active_error is not None:
                active_error.add_note(
                    f"Transport rollback after preparation failure also failed: {exc}"
                )
                return
            raise UpdateCleanupError(
                f"Transport rollback after preparation failure failed: {exc}"
            ) from exc
