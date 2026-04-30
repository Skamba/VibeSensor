"""Mutable update-status session separated from transition/logging policy."""

from __future__ import annotations

import time

from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdatePhase,
    UpdateRequest,
    UpdateRuntimeDetails,
    UpdateState,
    UpdateTerminalState,
)

from .state_store import UpdateStateStore

__all__ = ["UpdateStatusSession"]


class UpdateStatusSession:
    """Own the mutable status snapshot and persistence side effects."""

    __slots__ = ("_state_store", "_status")

    def __init__(
        self,
        *,
        state_store: UpdateStateStore,
        status: UpdateJobStatus | None = None,
    ) -> None:
        self._state_store = state_store
        self._status = status or UpdateJobStatus()

    @property
    def status(self) -> UpdateJobStatus:
        return self._status

    def persist(self) -> None:
        self._state_store.save(self._status)

    def touch(self, *, phase_changed: bool = False) -> float:
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
            terminal_state=None,
            runtime=previous_runtime,
        )
        self.persist()

    def transition(self, phase: UpdatePhase) -> None:
        self._status.phase = phase
        self.touch(phase_changed=True)
        self.persist()

    def set_runtime(self, runtime: UpdateRuntimeDetails) -> None:
        self._status.runtime = runtime
        self.touch()

    def set_uplink_interface(self, interface_name: str | None) -> None:
        self._status.uplink_interface = interface_name
        self.touch()
        self.persist()

    def mark_failed(self, terminal_state: UpdateTerminalState | None = None) -> None:
        self._status.state = UpdateState.failed
        self._status.terminal_state = terminal_state
        self.touch()
        self.persist()

    def mark_interrupted(self) -> None:
        self._status.state = UpdateState.failed
        self._status.finished_at = time.time()
        self.touch()
        self.persist()

    def begin_success(self) -> None:
        now = time.time()
        self._status.state = UpdateState.success
        self._status.phase = UpdatePhase.done
        self._status.last_success_at = now
        self._status.exit_code = 0
        self._status.terminal_state = UpdateTerminalState.success
        self._status.phase_started_at = now
        self._status.updated_at = now

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
