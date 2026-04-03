"""Update status coordination over phase policy, redaction, and persistence."""

from __future__ import annotations

from vibesensor.use_cases.updates.models import (
    UpdateIssue,
    UpdateJobStatus,
    UpdatePhase,
    UpdateRequest,
    UpdateRuntimeDetails,
    UpdateState,
)
from vibesensor.use_cases.updates.runner import sanitize_log_line

from .log_buffer import UpdateLogBuffer
from .secret_redactor import UpdateSecretRedactor
from .session import UpdateStatusSession
from .state_machine import UpdatePhaseStateMachine, UpdatePhaseTransitionError
from .state_store import UpdateStateStore


def _phase_name(phase: UpdatePhase | str) -> str:
    """Normalize enum-backed phases to their persisted string representation."""

    return phase.value if isinstance(phase, UpdatePhase) else phase


class UpdateStatusTracker:
    """Own update job state, persistence, redaction, and issue reporting."""

    __slots__ = (
        "_log_buffer",
        "_phase_state_machine",
        "_secret_redactor",
        "_session",
    )

    def __init__(
        self,
        *,
        state_store: UpdateStateStore,
        status: UpdateJobStatus | None = None,
        phase_state_machine: UpdatePhaseStateMachine | None = None,
        log_buffer: UpdateLogBuffer | None = None,
        secret_redactor: UpdateSecretRedactor | None = None,
    ) -> None:
        self._session = UpdateStatusSession(
            state_store=state_store,
            status=status,
        )
        self._log_buffer = log_buffer or UpdateLogBuffer()
        self._secret_redactor = secret_redactor or UpdateSecretRedactor()
        self._phase_state_machine = phase_state_machine or UpdatePhaseStateMachine()

    @property
    def status(self) -> UpdateJobStatus:
        return self._session.status

    def persist(self) -> None:
        """Flush the current in-memory status snapshot to the state store."""

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

    def log(self, msg: str) -> None:
        sanitized = self.redact(sanitize_log_line(msg))
        self._log_buffer.append(self.status, sanitized)
        self._session.touch()

    def add_issue(self, phase: UpdatePhase | str, message: str, detail: str = "") -> None:
        self._log_buffer.add_issue(
            self.status,
            UpdateIssue(
                phase=_phase_name(phase),
                message=self.redact(message),
                detail=self.redact(sanitize_log_line(detail)),
            ),
        )
        self._session.touch()

    def extend_issues(self, issues: list[UpdateIssue]) -> None:
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

    def fail(self, phase: UpdatePhase | str, message: str, detail: str = "") -> None:
        self.add_issue(phase, message, detail)
        self._session.mark_failed()

    def mark_interrupted(self, message: str) -> None:
        self._log_buffer.add_issue(
            self.status,
            UpdateIssue(phase="startup", message=message),
        )
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
        self.persist()

    def finish_cleanup(self) -> None:
        """Finalize status after cleanup, preserving successful end states."""

        self._session.finish_cleanup()
