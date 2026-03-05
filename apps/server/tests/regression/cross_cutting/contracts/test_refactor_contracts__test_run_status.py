"""Cross-module refactor-contract regressions.

Validates that the refactored code preserves behaviour while being more
maintainable than the originals.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vibesensor.history_db import HistoryDB, RunStatus
from vibesensor.protocol import HelloMessage
from vibesensor.registry import (
    ClientRegistry,
)

_CLIENT_ID = bytes.fromhex("aabbccddeeff")

_SAMPLES_200X3 = np.zeros((200, 3), dtype=np.int16)


@pytest.fixture()
def db(tmp_path: Path) -> HistoryDB:
    return HistoryDB(tmp_path / "history.db")


@pytest.fixture()
def registry(db: HistoryDB) -> ClientRegistry:
    return ClientRegistry(db=db)


def _hello(client_id: bytes = _CLIENT_ID, **overrides: object) -> HelloMessage:
    defaults: dict[str, object] = {
        "client_id": client_id,
        "control_port": 9010,
        "sample_rate_hz": 800,
        "name": "node-1",
        "firmware_version": "fw",
    }
    defaults.update(overrides)
    return HelloMessage(**defaults)  # type: ignore[arg-type]


_EXPECTED_ROW_KEYS = {
    "id",
    "mac_address",
    "name",
    "connected",
    "location",
    "firmware_version",
    "sample_rate_hz",
    "frame_samples",
    "last_seen_age_ms",
    "data_addr",
    "control_addr",
    "frames_total",
    "dropped_frames",
    "duplicates_received",
    "queue_overflow_drops",
    "parse_errors",
    "server_queue_drops",
    "latest_metrics",
    "last_ack_cmd_seq",
    "last_ack_status",
    "reset_count",
    "last_reset_time",
    "timing_health",
}


class TestRunStatus:
    """Verify RunStatus constants match database values."""

    @pytest.mark.parametrize(
        "attr, expected",
        [
            ("RECORDING", "recording"),
            ("ANALYZING", "analyzing"),
            ("COMPLETE", "complete"),
            ("ERROR", "error"),
        ],
    )
    def test_status_value(self, attr: str, expected: str) -> None:
        assert getattr(RunStatus, attr) == expected

    def test_history_db_uses_run_status(self, db: HistoryDB) -> None:
        """delete_run_if_safe should return RunStatus.ANALYZING for analyzing runs."""
        db.create_run("run-1", "2024-01-01T00:00:00Z", {})
        db.finalize_run("run-1", "2024-01-01T00:01:00Z")
        deleted, reason = db.delete_run_if_safe("run-1")
        assert not deleted
        assert reason == RunStatus.ANALYZING
