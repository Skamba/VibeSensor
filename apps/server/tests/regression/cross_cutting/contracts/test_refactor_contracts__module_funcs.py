"""Cross-module refactor-contract regressions.

Validates that the refactored code preserves behaviour while being more
maintainable than the originals.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pytest

from vibesensor.history_db import HistoryDB
from vibesensor.protocol import HelloMessage
from vibesensor.registry import (
    ClientRegistry,
)
from vibesensor.release_fetcher import (
    DOWNLOAD_CHUNK_BYTES,
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


def test_download_chunk_constant() -> None:
    assert DOWNLOAD_CHUNK_BYTES == 1024 * 1024  # 1 MB
    assert DOWNLOAD_CHUNK_BYTES > 0


def test_cursor_has_return_annotation() -> None:
    """_cursor should have a return type annotation."""
    sig = inspect.signature(HistoryDB._cursor)
    assert sig.return_annotation is not inspect.Parameter.empty
