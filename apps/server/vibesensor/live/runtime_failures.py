"""Shared operational failure types used across runtime and adapters."""

from __future__ import annotations

from vibesensor.shared.failure_utils import bounded_failure_message

__all__ = ["BroadcastTickLoopFailure", "ProcessingLoopFailure"]


class BroadcastTickLoopFailure(RuntimeError):
    """Repeated broadcast-loop failure escalated to outer runtime supervision."""

    def __init__(self, *, consecutive_failures: int, cause: Exception) -> None:
        self.consecutive_failures = consecutive_failures
        self.cause = cause
        super().__init__(
            "WebSocket broadcast tick failed "
            f"{consecutive_failures} consecutive times: {bounded_failure_message(cause)}"
        )


class ProcessingLoopFailure(RuntimeError):
    """Persistent processing-loop failure escalated to outer runtime supervision."""

    def __init__(
        self,
        *,
        fatal_backoff_cycles: int,
        failure_category: str,
        cause: Exception,
    ) -> None:
        self.fatal_backoff_cycles = fatal_backoff_cycles
        self.failure_category = failure_category
        self.cause = cause
        super().__init__(
            "Processing loop remained unhealthy after "
            f"{fatal_backoff_cycles} fatal backoff cycles "
            f"({failure_category}): {bounded_failure_message(cause)}"
        )
