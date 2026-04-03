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

from .state_machine import UpdatePhaseStateMachine, UpdatePhaseTransitionError
from .state_store import UpdateStateStore

_LOG_TAIL_MAX = 200
_LOG_TAIL_TRIM_TO = 100


def _phase_name(phase: UpdatePhase | str) -> str:
    """Normalize enum-backed phases to their persisted string representation."""

    return phase.value if isinstance(phase, UpdatePhase) else phase


class UpdateStatusTracker:
    """Own update job state, persistence, redaction, and issue reporting."""

    __slots__ = ("_phase_state_machine", "_redact_secrets", "_state_store", "_status")

    def __init__(
        self,
        *,
        state_store: UpdateStateStore,
        status: UpdateJobStatus | None = None,
        phase_state_machine: UpdatePhaseStateMachine | None = None,
    ) -> None:
        self._state_store = state_store
        self._status = status or UpdateJobStatus()
        self._redact_secrets: set[str] = set()
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
        """Redact positional values that follow sensitive command-line flags."""

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

    def log(self, msg: str) -> None:
        sanitized = self.redact(sanitize_log_line(msg))
        log_tail = self._status.log_tail
        log_tail.append(sanitized)
        if len(log_tail) > _LOG_TAIL_MAX:
            del log_tail[:-_LOG_TAIL_TRIM_TO]
        self._touch()

    def add_issue(self, phase: UpdatePhase | str, message: str, detail: str = "") -> None:
        self._status.issues.append(
            UpdateIssue(
                phase=_phase_name(phase),
                message=self.redact(message),
                detail=self.redact(sanitize_log_line(detail)),
            ),
        )
        self._touch()

    def extend_issues(self, issues: list[UpdateIssue]) -> None:
        for issue in issues:
            self._status.issues.append(
                UpdateIssue(
                    phase=issue.phase,
                    message=self.redact(issue.message),
                    detail=self.redact(issue.detail),
                ),
            )
        if issues:
            self._touch()

    def fail(self, phase: UpdatePhase | str, message: str, detail: str = "") -> None:
        self.add_issue(phase, message, detail)
        self._status.state = UpdateState.failed
        self._touch()
        self.persist()

    def mark_interrupted(self, message: str) -> None:
        self._status.state = UpdateState.failed
        self._status.finished_at = time.time()
        self._status.issues.append(UpdateIssue(phase="startup", message=message))
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
