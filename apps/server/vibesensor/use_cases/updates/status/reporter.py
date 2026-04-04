"""Terminal updater state reporting over the mutable status tracker."""

from __future__ import annotations

from vibesensor.shared.exceptions import UpdateError
from vibesensor.use_cases.updates.models import UpdateState

from .tracker import UpdateStatusTracker

__all__ = ["UpdateTerminalStateReporter"]


class UpdateTerminalStateReporter:
    """Own terminal updater state transitions from explicit workflow outcomes."""

    __slots__ = ("_status",)

    def __init__(self, *, status: UpdateStatusTracker) -> None:
        self._status = status

    def fail(self, error: UpdateError, *, default_phase: str) -> None:
        if self._status.status.state is UpdateState.idle:
            return
        phase = error.phase or self._status.status.phase.value or default_phase
        self._status.fail(
            phase,
            str(error),
            error.detail,
            log_message=error.log_message,
        )

    def fail_timeout(self, *, timeout_s: float) -> None:
        if self._status.status.state is UpdateState.idle:
            return
        message = f"Update timed out after {timeout_s}s"
        self._status.fail("timeout", message, log_message=message)

    def fail_cancelled(self, *, message: str = "Update was cancelled") -> None:
        if self._status.status.state is UpdateState.idle:
            return
        self._status.fail("cancelled", message, log_message="Update cancelled")

    def mark_interrupted(self, message: str, detail: str = "") -> None:
        self._status.mark_interrupted(message, detail)

    def mark_success(self, message: str) -> None:
        self._status.mark_success(message)
