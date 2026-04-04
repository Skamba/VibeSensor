from __future__ import annotations

from pathlib import Path

from vibesensor.use_cases.updates.status import (
    UpdateStateStore,
    UpdateStatusTracker,
    build_update_status_tracker,
)


def build_update_status_harness(state_path: Path) -> UpdateStatusTracker:
    return build_update_status_tracker(state_store=UpdateStateStore(state_path))
