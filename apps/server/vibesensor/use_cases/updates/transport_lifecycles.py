"""Canonical updater transport lifecycle and prepared-transport boundaries."""

from __future__ import annotations

from typing import Protocol

from vibesensor.use_cases.updates.models import UpdateJobStatus, UpdateRequest, UpdateTransport

__all__ = [
    "PreparedUpdateTransport",
    "UpdateTransportLifecycle",
    "UpdateTransportLifecycles",
]


class PreparedUpdateTransport(Protocol):
    """Post-prepare transport handle used by the main update workflow."""

    transport: UpdateTransport

    async def complete_success(self, message: str) -> None:
        """Finalize a successful update for this transport."""
        ...

    async def cleanup_after_update(self) -> None:
        """Run post-workflow cleanup for this prepared transport."""
        ...


class UpdateTransportLifecycle(PreparedUpdateTransport, Protocol):
    """Per-transport lifecycle surface for preparation, cleanup, and recovery."""

    async def prepare(self, request: UpdateRequest) -> PreparedUpdateTransport:
        """Prepare this transport before release work starts and return its handle."""
        ...

    async def abort_preparation(self) -> None:
        """Rollback any partial transport setup after prepare-time failure."""
        ...

    async def recover_interrupted_update(self, status: UpdateJobStatus) -> None:
        """Recover transport-owned state after an interrupted update job."""
        ...


class UpdateTransportLifecycles:
    """Resolve canonical updater transport lifecycles from requests or persisted state."""

    __slots__ = ("_lifecycles",)

    def __init__(
        self,
        *,
        wifi: UpdateTransportLifecycle,
        usb_internet: UpdateTransportLifecycle,
    ) -> None:
        self._lifecycles: dict[UpdateTransport, UpdateTransportLifecycle] = {
            UpdateTransport.wifi: wifi,
            UpdateTransport.usb_internet: usb_internet,
        }

    def for_request(self, request: UpdateRequest) -> UpdateTransportLifecycle:
        return self._lifecycles[request.transport]

    def for_transport(self, transport: UpdateTransport) -> UpdateTransportLifecycle:
        return self._lifecycles[transport]

    def for_status(self, status: UpdateJobStatus) -> UpdateTransportLifecycle:
        return self.for_transport(status.transport)
