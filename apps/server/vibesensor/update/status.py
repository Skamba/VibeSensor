"""Job status tracking and persistence for updater runs."""

from __future__ import annotations

import time

from ..json_types import JsonObject
from .models import UpdateIssue, UpdateJobStatus, UpdatePhase, UpdateState
from .runner import sanitize_log_line
from .state_store import UpdateStateStore

_LOG_TAIL_MAX = 200
_LOG_TAIL_TRIM_TO = 100


def _phase_name(phase: UpdatePhase | str) -> str:
    return phase.value if isinstance(phase, UpdatePhase) else phase


class UpdateStatusTracker:
    """Owns update job state, persistence, redaction, and issue reporting."""

    __slots__ = ("_state_store", "_status", "_redact_secrets")

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

    def persist(self) -> None:
        self._state_store.save(self._status)

    def _touch(self, *, phase_changed: bool = False) -> float:
        now = time.time()
        self._status.updated_at = now
        if phase_changed:
            self._status.phase_started_at = now
        return now

    def start_job(self, ssid: str) -> None:
        previous_runtime = dict(self._status.runtime)
        now = time.time()
        self._status = UpdateJobStatus(
            state=UpdateState.running,
            phase=UpdatePhase.validating,
            started_at=now,
            phase_started_at=now,
            updated_at=now,
            ssid=ssid,
            last_success_at=self._status.last_success_at,
            runtime=previous_runtime,
        )
        self.persist()

    def transition(self, phase: UpdatePhase) -> None:
        self._status.phase = phase
        self._touch(phase_changed=True)
        self.persist()

    def set_runtime(self, runtime: JsonObject) -> None:
        self._status.runtime = runtime
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
        self.persist()

    def add_issue(self, phase: UpdatePhase | str, message: str, detail: str = "") -> None:
        self._status.issues.append(
            UpdateIssue(
                phase=_phase_name(phase),
                message=self.redact(message),
                detail=self.redact(sanitize_log_line(detail)),
            )
        )
        self._touch()
        self.persist()

    def extend_issues(self, issues: list[UpdateIssue]) -> None:
        for issue in issues:
            self._status.issues.append(
                UpdateIssue(
                    phase=issue.phase,
                    message=self.redact(issue.message),
                    detail=self.redact(issue.detail),
                )
            )
        if issues:
            self._touch()
            self.persist()

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
        now = time.time()
        self._status.finished_at = self._status.finished_at or now
        if self._status.state == UpdateState.running:
            self._status.state = UpdateState.failed
        if self._status.state != UpdateState.failed:
            self._status.phase = UpdatePhase.done
            self._status.phase_started_at = now
        self._status.updated_at = now
        self.persist()
