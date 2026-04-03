"""Observation and audit recording for update job status."""

from __future__ import annotations

from vibesensor.use_cases.updates.models import UpdateIssue, UpdateJobStatus, UpdateRuntimeDetails
from vibesensor.use_cases.updates.runner import sanitize_log_line

from .log_buffer import UpdateLogBuffer
from .secret_redactor import UpdateSecretRedactor
from .session import UpdateStatusSession

__all__ = ["UpdateStatusRecorder"]


class UpdateStatusRecorder:
    """Record logs, issues, runtime details, and secret redaction without phase control."""

    __slots__ = ("_log_buffer", "_secret_redactor", "_session")

    def __init__(
        self,
        *,
        session: UpdateStatusSession,
        log_buffer: UpdateLogBuffer | None = None,
        secret_redactor: UpdateSecretRedactor | None = None,
    ) -> None:
        self._session = session
        self._log_buffer = log_buffer or UpdateLogBuffer()
        self._secret_redactor = secret_redactor or UpdateSecretRedactor()

    @property
    def status(self) -> UpdateJobStatus:
        return self._session.status

    def set_runtime(self, runtime: UpdateRuntimeDetails) -> None:
        self._session.set_runtime(runtime)

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

    def add_issue(self, phase: str, message: str, detail: str = "") -> None:
        self._log_buffer.add_issue(
            self.status,
            UpdateIssue(
                phase=phase,
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
