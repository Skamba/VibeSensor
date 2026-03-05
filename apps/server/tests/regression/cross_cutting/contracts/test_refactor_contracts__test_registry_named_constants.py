"""Cross-module refactor-contract regressions.

Validates that the refactored code preserves behaviour while being more
maintainable than the originals.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vibesensor.history_db import HistoryDB
from vibesensor.protocol import DataMessage, HelloMessage
from vibesensor.registry import (
    _JITTER_EMA_ALPHA,
    _RESTART_SEQ_GAP,
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


class TestRegistryNamedConstants:
    """Verify magic numbers were extracted to named constants."""

    def test_restart_seq_gap_is_int(self) -> None:
        assert isinstance(_RESTART_SEQ_GAP, int)
        assert _RESTART_SEQ_GAP > 0

    def test_jitter_ema_alpha_is_float(self) -> None:
        assert isinstance(_JITTER_EMA_ALPHA, float)
        assert 0 < _JITTER_EMA_ALPHA < 1

    def test_restart_seq_gap_value(self) -> None:
        """Value must be 1000 to match the original literal."""
        assert _RESTART_SEQ_GAP == 1000

    def test_jitter_ema_alpha_value(self) -> None:
        """Value must be 0.2 to match the original literal."""
        assert _JITTER_EMA_ALPHA == 0.2

    def test_restart_detection_uses_named_constant(self, registry: ClientRegistry) -> None:
        """Sending a seq far below last_seq should trigger reset detection,
        proving _RESTART_SEQ_GAP is wired into the logic."""
        registry.update_from_hello(_hello(), ("10.4.0.2", 9010), now=1.0)

        high_seq = _RESTART_SEQ_GAP + 100
        msg_high = DataMessage(
            client_id=_CLIENT_ID, seq=high_seq, t0_us=10, sample_count=200, samples=_SAMPLES_200X3
        )
        registry.update_from_data(msg_high, ("10.4.0.2", 50000), now=2.0)

        msg_low = DataMessage(
            client_id=_CLIENT_ID, seq=0, t0_us=20, sample_count=200, samples=_SAMPLES_200X3
        )
        result = registry.update_from_data(msg_low, ("10.4.0.2", 50000), now=3.0)
        assert result.reset_detected

    def test_ema_smoothing_uses_named_constant(self, registry: ClientRegistry) -> None:
        """Verify timing jitter EMA uses the named constant alpha value."""
        client_id = bytes.fromhex("112233445566")

        registry.update_from_hello(
            _hello(client_id, frame_samples=200), ("10.4.0.2", 9010), now=1.0
        )

        msg0 = DataMessage(
            client_id=client_id, seq=0, t0_us=0, sample_count=200, samples=_SAMPLES_200X3
        )
        registry.update_from_data(msg0, ("10.4.0.2", 50000), now=2.0)

        # Expected delta = 200/800 * 1e6 = 250000 µs
        # Actual delta = 300000 µs → jitter = 50000 µs
        msg1 = DataMessage(
            client_id=client_id, seq=1, t0_us=300_000, sample_count=200, samples=_SAMPLES_200X3
        )
        registry.update_from_data(msg1, ("10.4.0.2", 50000), now=3.0)

        record = registry.get(client_id.hex())
        # With alpha=0.2 and initial EMA=0, first update should be:
        # (1-0.2)*0 + 0.2*50000 = 10000
        expected = _JITTER_EMA_ALPHA * 50000.0
        assert record is not None
        assert abs(record.timing_jitter_us_ema - expected) < 0.01
