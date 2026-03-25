"""GPS transport connection lifecycle: reconnect policy and state transitions.

Owns reconnect backoff and the snapshot-field changes produced by each
connection lifecycle event (connect, clean disconnect, error disconnect).
The main transport loop delegates lifecycle decisions here while remaining
responsible for I/O orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

GPS_DISABLED_POLL_S: float = 5.0
"""Sleep interval when GPS is disabled."""

GPS_RECONNECT_DELAY_S: float = 2.0
"""Initial delay before reconnecting after a GPS connection loss."""

GPS_CONNECT_TIMEOUT_S: float = 3.0
GPS_READ_TIMEOUT_S: float = 3.0
GPS_RECONNECT_MAX_DELAY_S: float = 15.0

_DISCONNECTED_FIELDS: dict[str, Any] = {
    "connection_state": "disconnected",
    "speed_snapshot": (None, None),
    "last_fix_mode": None,
    "last_epx_m": None,
    "last_epy_m": None,
    "last_epv_m": None,
    "zero_speed_streak": 0,
    "device_info": None,
}


@dataclass(frozen=True, slots=True)
class LifecycleTransition:
    """Snapshot field changes produced by a lifecycle event."""

    changes: dict[str, Any]
    sleep_before_retry: float | None = None
    """When set, the caller should sleep this many seconds before retrying."""


class TransportLifecycle:
    """Reconnect policy and state-transition producer for the GPS transport loop.

    Tracks exponential backoff internally.  Each ``on_*`` method returns a
    :class:`LifecycleTransition` whose *changes* dict can be applied
    directly to the transport snapshot via ``_replace_snapshot(**t.changes)``.
    """

    def __init__(
        self,
        initial_delay: float = GPS_RECONNECT_DELAY_S,
        max_delay: float = GPS_RECONNECT_MAX_DELAY_S,
        backoff_factor: float = 2.0,
    ) -> None:
        self._initial_delay = initial_delay
        self._max_delay = max_delay
        self._backoff_factor = backoff_factor
        self._current_delay = initial_delay

    @property
    def reconnect_delay(self) -> float:
        """Current reconnect delay (before next backoff step)."""
        return self._current_delay

    def on_connected(self) -> LifecycleTransition:
        """Successful connection established."""
        self._current_delay = self._initial_delay
        return LifecycleTransition(
            changes={
                "connection_state": "connected",
                "last_error": None,
                "current_reconnect_delay": self._initial_delay,
            },
        )

    def on_stream_disconnected(self) -> LifecycleTransition:
        """Clean end-of-stream (remote closed the connection)."""
        self._current_delay = self._initial_delay
        return LifecycleTransition(changes=dict(_DISCONNECTED_FIELDS))

    def on_connection_error(self, exc: BaseException) -> LifecycleTransition:
        """Connection lost or timed out.  Advances the backoff timer."""
        delay = self._current_delay
        changes = {
            **_DISCONNECTED_FIELDS,
            "last_error": str(exc) or type(exc).__name__,
            "current_reconnect_delay": delay,
        }
        self._current_delay = min(self._max_delay, delay * self._backoff_factor)
        return LifecycleTransition(changes=changes, sleep_before_retry=delay)

    def reset_delay(self) -> None:
        """Reset delay after a successful read session (no error)."""
        self._current_delay = self._initial_delay
