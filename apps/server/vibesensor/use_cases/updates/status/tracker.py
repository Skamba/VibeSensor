"""Public update-status bundle over explicit state control and observation services."""

from __future__ import annotations

from vibesensor.use_cases.updates.models import (
    UpdateIssue,
    UpdateJobStatus,
    UpdatePhase,
    UpdateRequest,
    UpdateRuntimeDetails,
)

from .log_buffer import UpdateLogBuffer
from .run_recorder import UpdateStatusRecorder
from .secret_redactor import UpdateSecretRedactor
from .session import UpdateStatusSession
from .state_controller import UpdateStatusController
from .state_machine import UpdatePhaseStateMachine
from .state_store import UpdateStateStore


class UpdateStatusTracker:
    """Compatibility facade over split update status controller and recorder services."""

    __slots__ = ("controller", "recorder")

    def __init__(
        self,
        *,
        state_store: UpdateStateStore,
        status: UpdateJobStatus | None = None,
        phase_state_machine: UpdatePhaseStateMachine | None = None,
        log_buffer: UpdateLogBuffer | None = None,
        secret_redactor: UpdateSecretRedactor | None = None,
    ) -> None:
        session = UpdateStatusSession(
            state_store=state_store,
            status=status,
        )
        self.controller = UpdateStatusController(
            session=session,
            phase_state_machine=phase_state_machine,
        )
        self.recorder = UpdateStatusRecorder(
            session=session,
            log_buffer=log_buffer,
            secret_redactor=secret_redactor,
        )

    @property
    def status(self) -> UpdateJobStatus:
        return self.controller.status

    def persist(self) -> None:
        """Flush the current in-memory status snapshot to the state store."""

        self.controller.persist()

    def start_job(self, request: UpdateRequest) -> None:
        self.controller.start_job(request)

    def transition(self, phase: UpdatePhase) -> None:
        self.controller.transition(phase)

    def set_runtime(self, runtime: UpdateRuntimeDetails) -> None:
        self.recorder.set_runtime(runtime)

    def set_uplink_interface(self, interface_name: str | None) -> None:
        self.controller.set_uplink_interface(interface_name)

    def track_secret(self, secret: str) -> None:
        self.recorder.track_secret(secret)

    def clear_secrets(self) -> None:
        self.recorder.clear_secrets()

    def redact(self, text: str) -> str:
        return self.recorder.redact(text)

    def redacted_args(self, args: list[str], sensitive_keys: set[str]) -> list[str]:
        return self.recorder.redacted_args(args, sensitive_keys)

    def log(self, msg: str) -> None:
        self.recorder.log(msg)

    def add_issue(self, phase: UpdatePhase | str, message: str, detail: str = "") -> None:
        phase_name = phase.value if isinstance(phase, UpdatePhase) else phase
        self.recorder.add_issue(phase_name, message, detail)

    def extend_issues(self, issues: list[UpdateIssue]) -> None:
        self.recorder.extend_issues(issues)

    def fail(self, phase: UpdatePhase | str, message: str, detail: str = "") -> None:
        self.add_issue(phase, message, detail)
        self.controller.mark_failed()

    def mark_interrupted(self, message: str) -> None:
        self.recorder.add_issue("startup", message)
        self.controller.mark_interrupted()

    def mark_success(self, message: str | None = None) -> None:
        self.controller.mark_success()
        if message:
            self.recorder.log(message)
        self.persist()

    def finish_cleanup(self) -> None:
        """Finalize status after cleanup, preserving successful end states."""

        self.controller.finish_cleanup()
