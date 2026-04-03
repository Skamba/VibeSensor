"""State and phase control for update job status."""

from __future__ import annotations

from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdatePhase,
    UpdateRequest,
    UpdateState,
)

from .session import UpdateStatusSession
from .state_machine import UpdatePhaseStateMachine, UpdatePhaseTransitionError

__all__ = ["UpdateStatusController"]


class UpdateStatusController:
    """Mutate update lifecycle state without owning logs, issues, or redaction."""

    __slots__ = ("_phase_state_machine", "_session")

    def __init__(
        self,
        *,
        session: UpdateStatusSession,
        phase_state_machine: UpdatePhaseStateMachine | None = None,
    ) -> None:
        self._session = session
        self._phase_state_machine = phase_state_machine or UpdatePhaseStateMachine()

    @property
    def status(self) -> UpdateJobStatus:
        return self._session.status

    def persist(self) -> None:
        self._session.persist()

    def start_job(self, request: UpdateRequest) -> None:
        self._session.start_job(request)

    def transition(self, phase: UpdatePhase) -> None:
        if self.status.state is not UpdateState.running:
            raise UpdatePhaseTransitionError(
                f"Cannot transition update phase while state is {self.status.state.value}",
            )
        self._phase_state_machine.ensure_transition(self.status.phase, phase)
        self._session.transition(phase)

    def set_uplink_interface(self, interface_name: str | None) -> None:
        self._session.set_uplink_interface(interface_name)

    def mark_failed(self) -> None:
        self._session.mark_failed()

    def mark_interrupted(self) -> None:
        self._session.mark_interrupted()

    def mark_success(self) -> None:
        if self.status.state is not UpdateState.running:
            raise UpdatePhaseTransitionError(
                f"Cannot mark update success while state is {self.status.state.value}",
            )
        self._phase_state_machine.ensure_success_completion(self.status.phase)
        self._session.begin_success()

    def finish_cleanup(self) -> None:
        self._session.finish_cleanup()
