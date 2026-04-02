"""Shared operational failure types used across runtime and adapters."""

from __future__ import annotations

from vibesensor.shared.failure_utils import bounded_failure_message

__all__ = ["BroadcastTickLoopFailure"]


class BroadcastTickLoopFailure(RuntimeError):
    """Repeated broadcast-loop failure escalated to outer runtime supervision."""

    def __init__(self, *, consecutive_failures: int, cause: Exception) -> None:
        self.consecutive_failures = consecutive_failures
        self.cause = cause
        super().__init__(
            "WebSocket broadcast tick failed "
            f"{consecutive_failures} consecutive times: {bounded_failure_message(cause)}"
        )
