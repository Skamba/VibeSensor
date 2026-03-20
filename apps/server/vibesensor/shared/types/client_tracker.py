"""Client-registry port used by recording use-cases.

This protocol captures the narrow ``ClientRegistry`` surface currently
consumed by ``use_cases/run/``. Issue ``#814`` will later consolidate these
focused protocols into a shared ``ports.py`` module.
"""

from __future__ import annotations

from typing import Protocol

__all__ = ["ClientTracker", "TrackedClient"]


class TrackedClient(Protocol):
    """Minimal active-client view consumed by recording helpers."""

    client_id: str
    name: str
    firmware_version: str
    sample_rate_hz: int
    location_code: str
    frames_total: int
    frames_dropped: int
    queue_overflow_drops: int


class ClientTracker(Protocol):
    """Client lookup operations needed by recording flows."""

    def get(self, client_id: str) -> TrackedClient | None: ...

    def active_client_ids(
        self,
        now: float | None = None,
        *,
        now_mono: float | None = None,
    ) -> list[str]: ...
