"""Canonical update-status runtime surface for one updater job."""

from __future__ import annotations

from collections.abc import Iterable

from vibesensor.use_cases.updates.models import (
    UpdateIssue,
    UpdateJobStatus,
    UpdatePhase,
    UpdateRequest,
    UpdateRuntimeDetails,
    UpdateState,
    UpdateTerminalState,
)
from vibesensor.use_cases.updates.runner import sanitize_log_line

from .log_buffer import UpdateLogBuffer
from .secret_redactor import UpdateSecretRedactor
from .session import UpdateStatusSession
from .state_machine import UpdatePhaseStateMachine, UpdatePhaseTransitionError
from .state_store import UpdateStateStore

__all__ = ["UpdateStatusTracker", "build_update_status_tracker"]


class UpdateStatusTracker:
    """Own update state transitions, status recording, and secret handling directly."""

    __slots__ = (
        "_log_buffer",
        "_phase_state_machine",
        "_secret_redactor",
        "_session",
    )

    def __init__(
        self,
        *,
        session: UpdateStatusSession,
        phase_state_machine: UpdatePhaseStateMachine | None = None,
        log_buffer: UpdateLogBuffer | None = None,
        secret_redactor: UpdateSecretRedactor | None = None,
    ) -> None:
        self._session = session
        self._phase_state_machine = phase_state_machine or UpdatePhaseStateMachine()
        self._log_buffer = log_buffer or UpdateLogBuffer()
        self._secret_redactor = secret_redactor or UpdateSecretRedactor()

    @property
    def status(self) -> UpdateJobStatus:
        return self._session.status

    def persist(self) -> None:
        self._session.persist()

    def start_job(self, request: UpdateRequest) -> None:
        self._session.start_job(request)

    def transition(self, phase: UpdatePhase) -> None:
        if self.status.state is not UpdateState.running:
            raise UpdatePhaseTransitionError(
                f"Cannot transition update phase while state is {self.status.state.value}",
            )
        self._phase_state_machine.ensure_transition(self.status.phase, phase)
        self._session.transition(phase)

    def set_runtime(self, runtime: UpdateRuntimeDetails) -> None:
        self._session.set_runtime(runtime)

    def set_uplink_interface(self, interface_name: str | None) -> None:
        self._session.set_uplink_interface(interface_name)

    def track_secret(self, secret: str) -> None:
        self._secret_redactor.track(secret)

    def clear_secrets(self) -> None:
        self._secret_redactor.clear()

    def redact(self, text: str) -> str:
        return self._secret_redactor.redact(text)

    def redacted_args(self, args: list[str], sensitive_keys: set[str]) -> list[str]:
        return self._secret_redactor.redacted_args(args, sensitive_keys)

    def log(self, message: str) -> None:
        sanitized = self.redact(sanitize_log_line(message))
        self._log_buffer.append(self.status, sanitized)
        self._session.touch()

    def add_issue(self, phase: UpdatePhase | str, message: str, detail: str = "") -> None:
        phase_name = phase.value if isinstance(phase, UpdatePhase) else phase
        self._log_buffer.add_issue(
            self.status,
            UpdateIssue(
                phase=phase_name,
                message=self.redact(message),
                detail=self.redact(sanitize_log_line(detail)),
            ),
        )
        self._session.touch()

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
            self._log_buffer.extend_issues(self.status, rewritten)
            self._session.touch()

    def mark_failed(self, terminal_state: UpdateTerminalState | None = None) -> None:
        self._session.mark_failed(terminal_state)

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
        self._session.mark_interrupted()

    def mark_success(self, message: str | None = None) -> None:
        if self.status.state is not UpdateState.running:
            raise UpdatePhaseTransitionError(
                f"Cannot mark update success while state is {self.status.state.value}",
            )
        self._phase_state_machine.ensure_success_completion(self.status.phase)
        self._session.begin_success()
        if message:
            self.log(message)
        self._session.persist()

    def finish_cleanup(self) -> None:
        self._session.finish_cleanup()


def build_update_status_tracker(
    *,
    state_store: UpdateStateStore,
    status: UpdateJobStatus | None = None,
    phase_state_machine: UpdatePhaseStateMachine | None = None,
    log_buffer: UpdateLogBuffer | None = None,
    secret_redactor: UpdateSecretRedactor | None = None,
) -> UpdateStatusTracker:
    """Build the canonical updater status surface around one mutable session."""

    return UpdateStatusTracker(
        session=UpdateStatusSession(
            state_store=state_store,
            status=status,
        ),
        phase_state_machine=phase_state_machine,
        log_buffer=log_buffer,
        secret_redactor=secret_redactor,
    )
