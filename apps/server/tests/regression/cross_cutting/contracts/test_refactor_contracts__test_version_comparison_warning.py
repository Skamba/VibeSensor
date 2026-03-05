"""Cross-module refactor-contract regressions.

Validates that the refactored code preserves behaviour while being more
maintainable than the originals.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from vibesensor.history_db import HistoryDB
from vibesensor.protocol import HelloMessage
from vibesensor.registry import (
    ClientRegistry,
)
from vibesensor.release_fetcher import (
    ReleaseFetcherConfig,
    ReleaseInfo,
    ServerReleaseFetcher,
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


class TestVersionComparisonWarning:
    def test_logs_warning_on_unparseable_version(self) -> None:
        """When packaging cannot parse versions, a warning should be logged
        instead of silently swallowing the exception."""
        config = ReleaseFetcherConfig(server_repo="owner/repo")
        fetcher = ServerReleaseFetcher(config)

        fake_release = ReleaseInfo(
            tag="server-v!!!INVALID!!!",
            version="!!!INVALID!!!",
            asset_name="vibesensor-0.0.0-py3-none-any.whl",
            asset_url="https://api.github.com/repos/owner/repo/releases/assets/1",
        )

        with (
            patch.object(fetcher, "find_latest_release", return_value=fake_release),
            patch("vibesensor.release_fetcher.LOGGER") as mock_logger,
        ):
            result = fetcher.check_update_available("1.0.0")

        # Should still return the release (treating unparseable as update)
        assert result is not None
        # Should have logged a warning
        mock_logger.warning.assert_called_once()
        assert "Could not compare versions" in mock_logger.warning.call_args[0][0]
