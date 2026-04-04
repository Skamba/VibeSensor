"""Canonical transport lifecycle coordination for updater workflows."""

from __future__ import annotations

import sys

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError, UpdateTransportError
from vibesensor.use_cases.updates.models import UpdateJobStatus, UpdateRequest
from vibesensor.use_cases.updates.transport_sessions import (
    UpdateTransportSession,
    UpdateTransportSessions,
)

__all__ = ["UpdateTransportCoordinator"]


class UpdateTransportCoordinator:
    """Resolve and drive transport lifecycle side effects through one boundary."""

    __slots__ = ("_sessions",)

    def __init__(self, *, sessions: UpdateTransportSessions) -> None:
        self._sessions = sessions

    async def prepare(self, request: UpdateRequest) -> UpdateTransportSession:
        session = self._sessions.for_request(request)
        try:
            await session.prepare(request)
        except UpdateTransportError:
            await self._abort_preparation(session)
            raise
        return session

    async def complete_success(
        self,
        transport_session: UpdateTransportSession,
        *,
        message: str,
    ) -> None:
        await transport_session.complete_success(message)

    async def cleanup_after_update(
        self,
        transport_session: UpdateTransportSession | None,
    ) -> None:
        if transport_session is None:
            return
        await transport_session.cleanup_after_update()

    async def recover_interrupted(self, status: UpdateJobStatus) -> None:
        await self._sessions.for_status(status).recover_interrupted_update()

    async def _abort_preparation(self, session: UpdateTransportSession) -> None:
        active_error = sys.exc_info()[1]
        try:
            await session.abort_preparation()
        except (OSError, UpdateError) as exc:
            if active_error is not None:
                active_error.add_note(
                    f"Transport rollback after preparation failure also failed: {exc}",
                )
                return
            raise UpdateCleanupError(
                f"Transport rollback after preparation failure failed: {exc}",
            ) from exc
