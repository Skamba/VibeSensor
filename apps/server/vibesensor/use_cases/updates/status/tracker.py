"""In-memory update status tracking plus persistence coordination."""

from __future__ import annotations

import time

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
        "_state_store",
        "_status",
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
        self._state_store = state_store
        self._status = status or UpdateJobStatus()
        self._log_buffer = log_buffer or UpdateLogBuffer()
        self._secret_redactor = secret_redactor or UpdateSecretRedactor()
        self._phase_state_machine = phase_state_machine or UpdatePhaseStateMachine()

    @property
    def status(self) -> UpdateJobStatus:
        return self._status

    def persist(self) -> None:
        """Flush the current in-memory status snapshot to the state store."""

        self._state_store.save(self._status)

    def _touch(self, *, phase_changed: bool = False) -> float:
        now = time.time()
        self._status.updated_at = now
        if phase_changed:
            self._status.phase_started_at = now
        return now

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
            runtime=previous_runtime,
        )
        self.persist()

    def transition(self, phase: UpdatePhase) -> None:
        if self._status.state is not UpdateState.running:
            raise UpdatePhaseTransitionError(
                f"Cannot transition update phase while state is {self._status.state.value}",
            )
        self._phase_state_machine.ensure_transition(self._status.phase, phase)
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
        self._log_buffer.append(self._status, sanitized)
        self._touch()

    def add_issue(self, phase: UpdatePhase | str, message: str, detail: str = "") -> None:
        self._log_buffer.add_issue(
            self._status,
            UpdateIssue(
                phase=_phase_name(phase),
                message=self.redact(message),
                detail=self.redact(sanitize_log_line(detail)),
            ),
        )
        self._touch()

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
            self._log_buffer.extend_issues(self._status, rewritten)
            self._touch()

    def fail(self, phase: UpdatePhase | str, message: str, detail: str = "") -> None:
        self.add_issue(phase, message, detail)
        self._status.state = UpdateState.failed
        self._touch()
        self.persist()

    def mark_interrupted(self, message: str) -> None:
        self._status.state = UpdateState.failed
        self._status.finished_at = time.time()
        self._log_buffer.add_issue(
            self._status,
            UpdateIssue(phase="startup", message=message),
        )
        self._touch()
        self.persist()

    def mark_success(self, message: str | None = None) -> None:
        if self._status.state is not UpdateState.running:
            raise UpdatePhaseTransitionError(
                f"Cannot mark update success while state is {self._status.state.value}",
            )
        self._phase_state_machine.ensure_success_completion(self._status.phase)
        now = time.time()
        self._status.state = UpdateState.success
        self._status.phase = UpdatePhase.done
        self._status.last_success_at = now
        self._status.exit_code = 0
        self._status.phase_started_at = now
        self._status.updated_at = now
        if message:
            self.log(message)
        self.persist()

    def finish_cleanup(self) -> None:
        """Finalize status after cleanup, preserving successful end states."""

        now = time.time()
        self._status.finished_at = self._status.finished_at or now
        if self._status.state == UpdateState.running:
            self._status.state = UpdateState.failed
        if self._status.state != UpdateState.failed:
            self._status.phase = UpdatePhase.done
            self._status.phase_started_at = now
        self._status.updated_at = now
        self.persist()
