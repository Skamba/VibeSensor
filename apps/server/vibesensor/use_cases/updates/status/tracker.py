"""Coherent status/runtime boundary for one update job."""

from __future__ import annotations

from collections.abc import Iterable

from vibesensor.use_cases.updates.models import (
    UpdateIssue,
    UpdateJobStatus,
    UpdatePhase,
    UpdateRequest,
    UpdateRuntimeDetails,
)

from .run_recorder import UpdateStatusRecorder
from .state_controller import UpdateStatusController

__all__ = ["UpdateStatusTracker"]


class UpdateStatusTracker:
    """Coordinate state transitions, logging, issues, and redaction through one surface."""

    __slots__ = ("_controller", "_recorder")

    def __init__(
        self,
        *,
        controller: UpdateStatusController,
        recorder: UpdateStatusRecorder,
    ) -> None:
        self._controller = controller
        self._recorder = recorder

    @property
    def status(self) -> UpdateJobStatus:
        return self._controller.status

    def persist(self) -> None:
        self._controller.persist()

    def start_job(self, request: UpdateRequest) -> None:
        self._controller.start_job(request)

    def transition(self, phase: UpdatePhase) -> None:
        self._controller.transition(phase)

    def set_runtime(self, runtime: UpdateRuntimeDetails) -> None:
        self._recorder.set_runtime(runtime)

    def set_uplink_interface(self, interface_name: str | None) -> None:
        self._controller.set_uplink_interface(interface_name)

    def track_secret(self, secret: str) -> None:
        self._recorder.track_secret(secret)

    def clear_secrets(self) -> None:
        self._recorder.clear_secrets()

    def redact(self, text: str) -> str:
        return self._recorder.redact(text)

    def redacted_args(self, args: list[str], sensitive_keys: set[str]) -> list[str]:
        return self._recorder.redacted_args(args, sensitive_keys)

    def log(self, message: str) -> None:
        self._recorder.log(message)

    def add_issue(self, phase: UpdatePhase | str, message: str, detail: str = "") -> None:
        phase_name = phase.value if isinstance(phase, UpdatePhase) else phase
        self._recorder.add_issue(phase_name, message, detail)

    def extend_issues(self, issues: Iterable[UpdateIssue]) -> None:
        self._recorder.extend_issues(list(issues))

    def fail(
        self,
        phase: UpdatePhase | str,
        message: str,
        detail: str = "",
        *,
        log_message: str | None = None,
    ) -> None:
        self.add_issue(phase, message, detail)
        if log_message:
            self.log(log_message)
        self._controller.mark_failed()

    def mark_interrupted(self, message: str, detail: str = "") -> None:
        self.add_issue("startup", message, detail)
        self._controller.mark_interrupted()
        self._controller.persist()

    def mark_success(self, message: str | None = None) -> None:
        self._controller.mark_success()
        if message:
            self.log(message)
        self._controller.persist()

    def finish_cleanup(self) -> None:
        self._controller.finish_cleanup()
