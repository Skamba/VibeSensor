from __future__ import annotations

from pathlib import Path

from vibesensor.use_cases.updates.status.payload_codec import UpdateStateStore
from vibesensor.use_cases.updates.status.tracker import UpdateStatusTracker


def build_update_status_harness(state_path: Path) -> UpdateStatusTracker:
    return UpdateStatusTracker(state_store=UpdateStateStore(state_path))
