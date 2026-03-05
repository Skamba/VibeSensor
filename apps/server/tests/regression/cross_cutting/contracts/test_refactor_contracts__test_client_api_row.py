"""Cross-module refactor-contract regressions.

Validates that the refactored code preserves behaviour while being more
maintainable than the originals.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vibesensor.history_db import HistoryDB
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


class TestClientApiRow:
    """Verify the extracted _client_api_row helper produces correct dicts."""

    def test_disconnected_row_has_all_keys(self) -> None:
        row = ClientRegistry._client_api_row(
            "aabbccddeeff",
            name="test-client",
            connected=False,
        )
        assert set(row.keys()) == _EXPECTED_ROW_KEYS

    def test_connected_row_has_same_keys(self) -> None:
        disconnected = ClientRegistry._client_api_row("aabbccddeeff", name="a", connected=False)
        connected = ClientRegistry._client_api_row(
            "aabbccddeeff",
            name="b",
            connected=True,
            location="front-left",
            firmware_version="1.0",
            sample_rate_hz=800,
        )
        assert set(disconnected.keys()) == set(connected.keys())

    def test_defaults_match_old_disconnected_shape(self) -> None:
        """Disconnected client row defaults match the original inline dict."""
        row = ClientRegistry._client_api_row("aabbccddeeff", name="test", connected=False)
        assert row["connected"] is False
        assert row["location"] == ""
        assert row["firmware_version"] == ""
        assert row["sample_rate_hz"] == 0
        assert row["frames_total"] == 0
        assert row["latest_metrics"] == {}
        assert row["timing_health"] == {}

    def test_snapshot_uses_helper(self, registry: ClientRegistry) -> None:
        """Verify snapshot_for_api returns rows with the same keys as _client_api_row."""
        registry.set_name("aabbccddeeff", "my-sensor")
        rows = registry.snapshot_for_api(now=1.0, now_mono=1.0)
        assert len(rows) == 1
        helper_row = ClientRegistry._client_api_row(
            "aabbccddeeff", name="my-sensor", connected=False
        )
        assert set(rows[0].keys()) == set(helper_row.keys())
