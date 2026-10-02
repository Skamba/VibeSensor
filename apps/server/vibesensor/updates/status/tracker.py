"""Canonical update-status tracker for one updater job.

The tracker owns the mutable :class:`UpdateJobStatus`, the phase-transition
policy, log/issue recording with secret redaction, persistence through the
:class:`UpdateStateStore`, and the terminal outcome reporting used by the
update manager (timeouts, cancellation, cleanup failures).
"""

from __future__ import annotations

import time
from collections.abc import Iterable

from vibesensor.common.exceptions import UpdateError
from vibesensor.updates.models import (
    UpdateIssue,
    UpdateJobStatus,
    UpdatePhase,
    UpdateRequest,
    UpdateRuntimeDetails,
    UpdateState,
    UpdateTerminalState,
)
from vibesensor.updates.runner import sanitize_log_line
from vibesensor.updates.status.payload_codec import UpdateStateStore

__all__ = ["UpdatePhaseTransitionError", "UpdateStatusTracker"]

_LOG_TAIL_MAX = 200
_LOG_TAIL_TRIM_TO = 100

_ALLOWED_PHASE_TRANSITIONS: dict[UpdatePhase, frozenset[UpdatePhase]] = {
    UpdatePhase.idle: frozenset(),
    UpdatePhase.validating: frozenset(
        {
            UpdatePhase.stopping_hotspot,
            UpdatePhase.connecting_usb_internet,
        },
    ),
    UpdatePhase.stopping_hotspot: frozenset(
        {
            UpdatePhase.connecting_wifi,
            UpdatePhase.restoring_hotspot,
        },
    ),
    UpdatePhase.connecting_wifi: frozenset(
        {
            UpdatePhase.checking,
            UpdatePhase.restoring_hotspot,
        },
    ),
    UpdatePhase.connecting_usb_internet: frozenset({UpdatePhase.checking}),
    UpdatePhase.checking: frozenset(
        {
            UpdatePhase.downloading,
            UpdatePhase.restoring_hotspot,
            UpdatePhase.done,
        },
    ),
    UpdatePhase.downloading: frozenset(
        {
            UpdatePhase.installing,
            UpdatePhase.restoring_hotspot,
        },
    ),
    UpdatePhase.installing: frozenset(
        {
            UpdatePhase.restoring_hotspot,
            UpdatePhase.done,
        },
    ),
    UpdatePhase.restoring_hotspot: frozenset({UpdatePhase.done}),
    UpdatePhase.done: frozenset(),
}

_SUCCESS_COMPLETION_PHASES = frozenset(
    {
        UpdatePhase.checking,
        UpdatePhase.installing,
        UpdatePhase.restoring_hotspot,
    },
)


class UpdatePhaseTransitionError(ValueError):
    """Raised when the update workflow attempts an invalid phase transition."""


class UpdateStatusTracker:
    """Own update state transitions, status recording, persistence, and secret handling."""

    __slots__ = ("_redact_secrets", "_state_store", "_status")

    def __init__(
        self,
        *,
        state_store: UpdateStateStore,
        status: UpdateJobStatus | None = None,
    ) -> None:
        self._state_store = state_store
        self._status = status or UpdateJobStatus()
        self._redact_secrets: set[str] = set()

    @property
    def status(self) -> UpdateJobStatus:
        return self._status

    # -- persistence -------------------------------------------------------

    def persist(self) -> None:
        self._state_store.save(self._status)

    def _touch(self, *, phase_changed: bool = False) -> float:
        now = time.time()
        self._status.updated_at = now
        if phase_changed:
            self._status.phase_started_at = now
        return now

    # -- job lifecycle -----------------------------------------------------

    def start_job(self, request: UpdateRequest) -> None:
        previous_runtime = self._status.runtime
        now = time.time()
        self._status = UpdateJobStatus(
            state=UpdateState.running,
            phase=UpdatePhase.validating,
            transport=request.transport,
            started_at=now,
            phase_started_at=now,
            updated_at=now,
            ssid=request.ssid,
            uplink_interface=None,
            last_success_at=self._status.last_success_at,
            terminal_state=None,
            runtime=previous_runtime,
        )
        self.persist()

    def transition(self, phase: UpdatePhase) -> None:
        if self._status.state is not UpdateState.running:
            raise UpdatePhaseTransitionError(
                f"Cannot transition update phase while state is {self._status.state.value}",
            )
        current = self._status.phase
        if phase != current and phase not in _ALLOWED_PHASE_TRANSITIONS[current]:
            raise UpdatePhaseTransitionError(
                f"Invalid update phase transition: {current.value} -> {phase.value}",
            )
        self._status.phase = phase
        self._touch(phase_changed=True)
        self.persist()

    def set_runtime(self, runtime: UpdateRuntimeDetails) -> None:
        self._status.runtime = runtime
        self._touch()

    def set_uplink_interface(self, interface_name: str | None) -> None:
        self._status.uplink_interface = interface_name
        self._touch()
        self.persist()

    def mark_failed(self, terminal_state: UpdateTerminalState | None = None) -> None:
        self._status.state = UpdateState.failed
        self._status.terminal_state = terminal_state
        self._touch()
        self.persist()

    def fail(
        self,
        phase: UpdatePhase | str,
        message: str,
        detail: str = "",
        *,
        log_message: str | None = None,
        terminal_state: UpdateTerminalState | None = None,
    ) -> None:
        self.add_issue(phase, message, detail)
        if log_message:
            self.log(log_message)
        self.mark_failed(terminal_state)

    def mark_interrupted(self, message: str, detail: str = "") -> None:
        self.add_issue("startup", message, detail)
        self._status.state = UpdateState.failed
        self._status.finished_at = time.time()
        self._touch()
        self.persist()

    def mark_success(self, message: str | None = None) -> None:
        if self._status.state is not UpdateState.running:
            raise UpdatePhaseTransitionError(
                f"Cannot mark update success while state is {self._status.state.value}",
            )
        if self._status.phase not in _SUCCESS_COMPLETION_PHASES:
            raise UpdatePhaseTransitionError(
                f"Cannot mark update success from phase {self._status.phase.value}",
            )
        now = time.time()
        self._status.state = UpdateState.success
        self._status.phase = UpdatePhase.done
        self._status.last_success_at = now
        self._status.exit_code = 0
        self._status.terminal_state = UpdateTerminalState.success
        self._status.phase_started_at = now
        self._status.updated_at = now
        if message:
            self.log(message)
        self.persist()

    def finish_cleanup(self) -> None:
        now = time.time()
        self._status.finished_at = self._status.finished_at or now
        if self._status.state == UpdateState.running:
            self._status.state = UpdateState.failed
        if self._status.state != UpdateState.failed:
            self._status.phase = UpdatePhase.done
            self._status.phase_started_at = now
        self._status.updated_at = now
        self.persist()

    # -- secrets -----------------------------------------------------------

    def track_secret(self, secret: str) -> None:
        self._redact_secrets = {secret} if secret else set()

    def clear_secrets(self) -> None:
        self._redact_secrets.clear()

    def redact(self, text: str) -> str:
        redacted = text
        for secret in self._redact_secrets:
            if secret:
                redacted = redacted.replace(secret, "***")
        return redacted

    def redacted_args(self, args: list[str], sensitive_keys: set[str]) -> list[str]:
        redacted: list[str] = []
        hide_next = False
        for raw_arg in args:
            arg = str(raw_arg)
            if hide_next:
                redacted.append("***")
                hide_next = False
                continue
            if arg.lower() in sensitive_keys:
                redacted.append(arg)
                hide_next = True
                continue
            if self._redact_secrets and arg in self._redact_secrets:
                redacted.append("***")
                continue
            redacted.append(arg)
        return redacted

    # -- log and issues ----------------------------------------------------

    def log(self, message: str) -> None:
        sanitized = self.redact(sanitize_log_line(message))
        self._status.log_tail.append(sanitized)
        if len(self._status.log_tail) > _LOG_TAIL_MAX:
            del self._status.log_tail[:-_LOG_TAIL_TRIM_TO]
        self._touch()

    def add_issue(self, phase: UpdatePhase | str, message: str, detail: str = "") -> None:
        phase_name = phase.value if isinstance(phase, UpdatePhase) else phase
        self._status.issues.append(
            UpdateIssue(
                phase=phase_name,
                message=self.redact(message),
                detail=self.redact(sanitize_log_line(detail)),
            ),
        )
        self._touch()

    def extend_issues(self, issues: Iterable[UpdateIssue]) -> None:
        rewritten = [
            UpdateIssue(
                phase=issue.phase,
                message=self.redact(issue.message),
                detail=self.redact(issue.detail),
            )
            for issue in issues
        ]
        if rewritten:
            self._status.issues.extend(rewritten)
            self._touch()

    # -- terminal outcomes reported by the update manager -------------------

    def fail_from_error(
        self,
        error: UpdateError,
        *,
        default_phase: str,
        terminal_state: UpdateTerminalState = UpdateTerminalState.workflow_failed,
    ) -> None:
        if self._status.state is UpdateState.idle:
            return
        phase = error.phase or self._status.phase.value or default_phase
        self.fail(
            phase,
            str(error),
            error.detail,
            log_message=error.log_message,
            terminal_state=terminal_state,
        )
        for note in getattr(error, "__notes__", ()):
            if str(note).startswith("Cleanup also failed:"):
                self.add_issue("cleanup", str(note))

    def fail_timeout(self, *, timeout_s: float) -> None:
        if self._status.state is UpdateState.idle:
            return
        message = f"Update timed out after {timeout_s}s"
        self.fail(
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
        if self._status.state is UpdateState.idle:
            return
        message = f"Update timed out after {timeout_s}s"
        self.add_issue("timeout", message)
        self.log(message)
        self.fail(
            "cleanup",
            str(cleanup_error),
            cleanup_error.detail,
            log_message=cleanup_error.log_message,
            terminal_state=UpdateTerminalState.timeout_cleanup_failed,
        )

    def fail_cancelled(self, *, message: str = "Update was cancelled") -> None:
        if self._status.state is UpdateState.idle:
            return
        self.fail(
            "cancelled",
            message,
            log_message="Update cancelled",
            terminal_state=UpdateTerminalState.cancelled_cleanly,
        )

    def fail_cancelled_cleanup_failed(self, cleanup_error: UpdateError) -> None:
        if self._status.state is UpdateState.idle:
            return
        self.add_issue("cancelled", "Update was cancelled")
        self.log("Update cancelled")
        self.fail(
            "cleanup",
            str(cleanup_error),
            cleanup_error.detail,
            log_message=cleanup_error.log_message,
            terminal_state=UpdateTerminalState.cancelled_cleanup_failed,
        )

    def fail_cleanup_failed(self, cleanup_error: UpdateError) -> None:
        if self._status.state is UpdateState.idle:
            return
        self.fail(
            cleanup_error.phase or "cleanup",
            str(cleanup_error),
            cleanup_error.detail,
            log_message=cleanup_error.log_message,
            terminal_state=UpdateTerminalState.cleanup_failed,
        )
