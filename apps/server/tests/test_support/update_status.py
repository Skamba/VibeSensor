from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vibesensor.use_cases.updates.models import (
    UpdateIssue,
    UpdateJobStatus,
    UpdatePhase,
    UpdateRequest,
    UpdateRuntimeDetails,
)
from vibesensor.use_cases.updates.status import (
    UpdateStateStore,
    UpdateStatusController,
    UpdateStatusRecorder,
    UpdateStatusServices,
    build_update_status_services,
)


@dataclass(frozen=True, slots=True)
class UpdateStatusHarness:
    services: UpdateStatusServices
    controller: UpdateStatusController
    recorder: UpdateStatusRecorder

    @property
    def tracker(self) -> UpdateStatusHarness:
        return self

    @property
    def status(self) -> UpdateJobStatus:
        return self.services.status

    def persist(self) -> None:
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

    def log(self, message: str) -> None:
        self.recorder.log(message)

    def add_issue(self, phase: UpdatePhase | str, message: str, detail: str = "") -> None:
        phase_name = phase.value if isinstance(phase, UpdatePhase) else phase
        self.recorder.add_issue(phase_name, message, detail)

    def extend_issues(self, issues: list[UpdateIssue]) -> None:
        self.recorder.extend_issues(issues)

    def mark_interrupted(self, message: str, detail: str = "") -> None:
        self.add_issue("startup", message, detail)
        self.controller.mark_interrupted()
        self.controller.persist()

    def mark_success(self, message: str | None = None) -> None:
        self.controller.mark_success()
        if message:
            self.recorder.log(message)
        self.controller.persist()

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
            self.recorder.log(log_message)
        self.controller.mark_failed()

    def finish_cleanup(self) -> None:
        self.controller.finish_cleanup()


def build_update_status_harness(state_path: Path) -> UpdateStatusHarness:
    services = build_update_status_services(state_store=UpdateStateStore(state_path))
    return UpdateStatusHarness(
        services=services,
        controller=services.controller,
        recorder=services.recorder,
    )
