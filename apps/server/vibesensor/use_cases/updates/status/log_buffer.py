"""Canonical in-memory log and issue aggregation for update status."""

from __future__ import annotations

from vibesensor.use_cases.updates.models import UpdateIssue, UpdateJobStatus

_LOG_TAIL_MAX = 200
_LOG_TAIL_TRIM_TO = 100


class UpdateLogBuffer:
    """Own log-tail trimming and issue aggregation independently from state mutation."""

    __slots__ = ()

    def append(self, status: UpdateJobStatus, message: str) -> None:
        status.log_tail.append(message)
        if len(status.log_tail) > _LOG_TAIL_MAX:
            del status.log_tail[:-_LOG_TAIL_TRIM_TO]

    def add_issue(self, status: UpdateJobStatus, issue: UpdateIssue) -> None:
        status.issues.append(issue)

    def extend_issues(self, status: UpdateJobStatus, issues: list[UpdateIssue]) -> None:
        status.issues.extend(issues)
