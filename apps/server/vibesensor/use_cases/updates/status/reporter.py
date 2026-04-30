"""Terminal updater state reporting over the mutable status tracker."""

from __future__ import annotations

from vibesensor.shared.exceptions import UpdateError
from vibesensor.use_cases.updates.models import UpdateState, UpdateTerminalState

from .tracker import UpdateStatusTracker

__all__ = ["UpdateTerminalStateReporter"]


class UpdateTerminalStateReporter:
    """Own terminal updater state transitions from explicit workflow outcomes."""

    __slots__ = ("_status",)

    def __init__(self, *, status: UpdateStatusTracker) -> None:
        self._status = status

    def fail(
        self,
        error: UpdateError,
        *,
        default_phase: str,
        terminal_state: UpdateTerminalState = UpdateTerminalState.workflow_failed,
    ) -> None:
        if self._status.status.state is UpdateState.idle:
            return
        phase = error.phase or self._status.status.phase.value or default_phase
        self._status.fail(
            phase,
            str(error),
            error.detail,
            log_message=error.log_message,
            terminal_state=terminal_state,
        )
        for note in getattr(error, "__notes__", ()):
            if str(note).startswith("Cleanup also failed:"):
                self._status.add_issue("cleanup", str(note))

    def fail_timeout(self, *, timeout_s: float) -> None:
        if self._status.status.state is UpdateState.idle:
            return
        message = f"Update timed out after {timeout_s}s"
        self._status.fail(
            "timeout",
            message,
            log_message=message,
            terminal_state=UpdateTerminalState.timeout,
        )

    def fail_timeout_cleanup_failed(
        self,
        cleanup_error: UpdateError,
        *,
        timeout_s: float,
    ) -> None:
        if self._status.status.state is UpdateState.idle:
            return
        message = f"Update timed out after {timeout_s}s"
        self._status.add_issue("timeout", message)
        self._status.log(message)
        self._status.fail(
            "cleanup",
            str(cleanup_error),
            cleanup_error.detail,
            log_message=cleanup_error.log_message,
            terminal_state=UpdateTerminalState.timeout_cleanup_failed,
        )

    def fail_cancelled(self, *, message: str = "Update was cancelled") -> None:
        if self._status.status.state is UpdateState.idle:
            return
        self._status.fail(
            "cancelled",
            message,
            log_message="Update cancelled",
            terminal_state=UpdateTerminalState.cancelled_cleanly,
        )

    def fail_cancelled_cleanup_failed(self, cleanup_error: UpdateError) -> None:
        if self._status.status.state is UpdateState.idle:
            return
        self._status.add_issue("cancelled", "Update was cancelled")
        self._status.log("Update cancelled")
        self._status.fail(
            "cleanup",
            str(cleanup_error),
            cleanup_error.detail,
            log_message=cleanup_error.log_message,
            terminal_state=UpdateTerminalState.cancelled_cleanup_failed,
        )

    def fail_cleanup_failed(self, cleanup_error: UpdateError) -> None:
        if self._status.status.state is UpdateState.idle:
            return
        self._status.fail(
            cleanup_error.phase or "cleanup",
            str(cleanup_error),
            cleanup_error.detail,
            log_message=cleanup_error.log_message,
            terminal_state=UpdateTerminalState.cleanup_failed,
        )

    def mark_interrupted(self, message: str, detail: str = "") -> None:
        self._status.mark_interrupted(message, detail)

    def mark_success(self, message: str) -> None:
        self._status.mark_success(message)
