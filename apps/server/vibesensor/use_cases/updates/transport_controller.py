"""Transport lifecycle boundary for update workflows."""

from __future__ import annotations

from vibesensor.use_cases.updates.models import UpdateRequest
from vibesensor.use_cases.updates.transport_sessions import (
    UpdateTransportSession,
    UpdateTransportSessions,
)

__all__ = ["UpdateTransportController"]


class UpdateTransportController:
    """Prepare transport sessions without owning release policy or installation."""

    __slots__ = ("_sessions",)

    def __init__(self, *, sessions: UpdateTransportSessions) -> None:
        self._sessions = sessions

    async def prepare(self, request: UpdateRequest) -> UpdateTransportSession | None:
        transport_session = self._sessions.for_request(request)
        if not await transport_session.prepare(request):
            return None
        return transport_session
