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

    def log(self, message: str) -> None:
        self.recorder.log(message)

    def extend_issues(self, issues: list[UpdateIssue]) -> None:
        self.recorder.extend_issues(issues)

    def mark_success(self, message: str | None = None) -> None:
        self.controller.mark_success()
        if message:
            self.recorder.log(message)
        self.controller.persist()

    def fail(self, phase: UpdatePhase | str, message: str, detail: str = "") -> None:
        phase_name = phase.value if isinstance(phase, UpdatePhase) else phase
        self.recorder.add_issue(phase_name, message, detail)
        self.controller.mark_failed()


def build_update_status_harness(state_path: Path) -> UpdateStatusHarness:
    services = build_update_status_services(state_store=UpdateStateStore(state_path))
    return UpdateStatusHarness(
        services=services,
        controller=services.controller,
        recorder=services.recorder,
    )
