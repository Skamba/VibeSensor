"""Canonical update-status service bundle."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.use_cases.updates.models import UpdateJobStatus

from .log_buffer import UpdateLogBuffer
from .run_recorder import UpdateStatusRecorder
from .secret_redactor import UpdateSecretRedactor
from .session import UpdateStatusSession
from .state_controller import UpdateStatusController
from .state_machine import UpdatePhaseStateMachine
from .state_store import UpdateStateStore
from .tracker import UpdateStatusTracker

__all__ = ["UpdateStatusServices", "build_update_status_services"]


@dataclass(frozen=True, slots=True)
class UpdateStatusServices:
    """Explicit status collaborators shared across updater runtime wiring."""

    session: UpdateStatusSession
    controller: UpdateStatusController
    recorder: UpdateStatusRecorder
    tracker: UpdateStatusTracker

    @property
    def status(self) -> UpdateJobStatus:
        return self.session.status


def build_update_status_services(
    *,
    state_store: UpdateStateStore,
    status: UpdateJobStatus | None = None,
    phase_state_machine: UpdatePhaseStateMachine | None = None,
    log_buffer: UpdateLogBuffer | None = None,
    secret_redactor: UpdateSecretRedactor | None = None,
) -> UpdateStatusServices:
    """Build the canonical status services without facade-style pass-throughs."""

    session = UpdateStatusSession(
        state_store=state_store,
        status=status,
    )
    controller = UpdateStatusController(
        session=session,
        phase_state_machine=phase_state_machine,
    )
    recorder = UpdateStatusRecorder(
        session=session,
        log_buffer=log_buffer,
        secret_redactor=secret_redactor,
    )
    return UpdateStatusServices(
        session=session,
        controller=controller,
        recorder=recorder,
        tracker=UpdateStatusTracker(
            controller=controller,
            recorder=recorder,
        ),
    )
