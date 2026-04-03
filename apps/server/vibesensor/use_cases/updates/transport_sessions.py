"""Canonical transport-session boundary for update job control flow."""

from __future__ import annotations

from typing import Protocol

from vibesensor.use_cases.updates.models import UpdateRequest, UpdateTransport


class UpdateTransportSession(Protocol):
    """One transport-specific update session with a uniform lifecycle."""

    transport: UpdateTransport

    async def prepare(self, request: UpdateRequest) -> None:
        """Prepare this transport for an update run before release work starts."""
        ...

    async def complete_success(self, message: str) -> None:
        """Finalize a successful update for this transport."""
        ...

    async def cleanup_after_update(self) -> None:
        """Run transport-specific cleanup after the update task exits."""
        ...

    async def recover_interrupted_update(self) -> None:
        """Recover transport-owned state after an interrupted update job."""
        ...


class UpdateTransportSessions:
    """Resolve canonical transport sessions from requests or persisted state."""

    __slots__ = ("_sessions",)

    def __init__(
        self,
        *,
        wifi: UpdateTransportSession,
        usb_internet: UpdateTransportSession,
    ) -> None:
        self._sessions: dict[UpdateTransport, UpdateTransportSession] = {
            UpdateTransport.wifi: wifi,
            UpdateTransport.usb_internet: usb_internet,
        }

    def for_request(self, request: UpdateRequest) -> UpdateTransportSession:
        return self.for_transport(request.transport)

    def for_transport(self, transport: UpdateTransport) -> UpdateTransportSession:
        return self._sessions[transport]
