from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vibesensor.use_cases.updates.status import (
    UpdateStateStore,
    UpdateStatusController,
    UpdateStatusRecorder,
    UpdateStatusTracker,
)


@dataclass(frozen=True, slots=True)
class UpdateStatusHarness:
    tracker: UpdateStatusTracker
    controller: UpdateStatusController
    recorder: UpdateStatusRecorder


def build_update_status_harness(state_path: Path) -> UpdateStatusHarness:
    tracker = UpdateStatusTracker(state_store=UpdateStateStore(state_path))
    return UpdateStatusHarness(
        tracker=tracker,
        controller=tracker.controller,
        recorder=tracker.recorder,
    )
