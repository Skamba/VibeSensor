"""Canonical updater transport boundaries for active setup and passive validation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from vibesensor.use_cases.updates.models import UpdateJobStatus, UpdateRequest, UpdateTransport

__all__ = [
    "ManagedUpdateTransportSession",
    "SetupUpdateTransportSession",
    "UpdateTransportSessions",
    "ValidatingUpdateTransportSession",
]


@runtime_checkable
class ManagedUpdateTransportSession(Protocol):
    """Post-prepare transport surface used by the main update workflow."""

    transport: UpdateTransport

    async def complete_success(self, message: str) -> None:
        """Finalize a successful update for this transport."""
        ...


@runtime_checkable
class SetupUpdateTransportSession(ManagedUpdateTransportSession, Protocol):
    """Transport that must actively set up and later unwind update-owned state."""

    async def prepare(self, request: UpdateRequest) -> None:
        """Prepare this transport before release work starts."""
        ...

    async def abort_preparation(self) -> None:
        """Rollback any partial transport setup after prepare-time failure."""
        ...

    async def cleanup_after_update(self) -> None:
        """Run transport-specific cleanup after the update task exits."""
        ...

    async def recover_interrupted_update(self) -> None:
        """Recover transport-owned state after an interrupted update job."""
        ...


@runtime_checkable
class ValidatingUpdateTransportSession(ManagedUpdateTransportSession, Protocol):
    """Transport that reuses an existing uplink and only validates readiness."""

    async def validate(self, request: UpdateRequest) -> None:
        """Validate an already-live transport before release work starts."""
        ...


type PreparingUpdateTransportSession = (
    SetupUpdateTransportSession | ValidatingUpdateTransportSession
)


class UpdateTransportSessions:
    """Resolve canonical updater transports from requests or persisted state."""

    __slots__ = ("_sessions",)

    def __init__(
        self,
        *,
        wifi: SetupUpdateTransportSession,
        usb_internet: ValidatingUpdateTransportSession,
    ) -> None:
        self._sessions: dict[UpdateTransport, PreparingUpdateTransportSession] = {
            UpdateTransport.wifi: wifi,
            UpdateTransport.usb_internet: usb_internet,
        }

    def for_request(self, request: UpdateRequest) -> PreparingUpdateTransportSession:
        return self._sessions[request.transport]

    def for_transport(self, transport: UpdateTransport) -> ManagedUpdateTransportSession:
        return self._sessions[transport]

    def for_status(self, status: UpdateJobStatus) -> ManagedUpdateTransportSession:
        return self.for_transport(status.transport)
