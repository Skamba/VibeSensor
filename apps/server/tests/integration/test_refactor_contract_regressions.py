# ruff: noqa: E402
from __future__ import annotations

"""Cross-module refactor-contract regressions.

Validates that the refactored code preserves behaviour while being more
maintainable than the originals.
"""


import inspect
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from vibesensor.firmware_cache import FirmwareCacheConfig, GitHubReleaseFetcher
from vibesensor.history_db import HistoryDB, RunStatus
from vibesensor.protocol import DataMessage, HelloMessage
from vibesensor.registry import (
    _JITTER_EMA_ALPHA,
    _RESTART_SEQ_GAP,
    ClientRegistry,
    ClientSnapshot,
)
from vibesensor.release_fetcher import (
    DOWNLOAD_CHUNK_BYTES,
    GitHubAPIClient,
    ReleaseFetcherConfig,
    ReleaseInfo,
    ServerReleaseFetcher,
)

# ---------------------------------------------------------------------------
# Shared constants / fixtures
# ---------------------------------------------------------------------------

_CLIENT_ID = bytes.fromhex("aabbccddeeff")
_SAMPLES_200X3 = np.zeros((200, 3), dtype=np.int16)


@pytest.fixture
def db(tmp_path: Path) -> HistoryDB:
    return HistoryDB(tmp_path / "history.db")


@pytest.fixture
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


# ---------------------------------------------------------------------------
# Fix 1 & 2: Named constants in registry.py
# ---------------------------------------------------------------------------


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
        proving _RESTART_SEQ_GAP is wired into the logic.
        """
        registry.update_from_hello(_hello(), ("10.4.0.2", 9010), now=1.0)

        high_seq = _RESTART_SEQ_GAP + 100
        msg_high = DataMessage(
            client_id=_CLIENT_ID,
            seq=high_seq,
            t0_us=10,
            sample_count=200,
            samples=_SAMPLES_200X3,
        )
        registry.update_from_data(msg_high, ("10.4.0.2", 50000), now=2.0)

        msg_low = DataMessage(
            client_id=_CLIENT_ID,
            seq=0,
            t0_us=20,
            sample_count=200,
            samples=_SAMPLES_200X3,
        )
        result = registry.update_from_data(msg_low, ("10.4.0.2", 50000), now=3.0)
        assert result.reset_detected

    def test_ema_smoothing_uses_named_constant(self, registry: ClientRegistry) -> None:
        """Verify timing jitter EMA uses the named constant alpha value."""
        client_id = bytes.fromhex("112233445566")

        registry.update_from_hello(
            _hello(client_id, frame_samples=200),
            ("10.4.0.2", 9010),
            now=1.0,
        )

        msg0 = DataMessage(
            client_id=client_id,
            seq=0,
            t0_us=0,
            sample_count=200,
            samples=_SAMPLES_200X3,
        )
        registry.update_from_data(msg0, ("10.4.0.2", 50000), now=2.0)

        # Expected delta = 200/800 * 1e6 = 250000 µs
        # Actual delta = 300000 µs → jitter = 50000 µs
        msg1 = DataMessage(
            client_id=client_id,
            seq=1,
            t0_us=300_000,
            sample_count=200,
            samples=_SAMPLES_200X3,
        )
        registry.update_from_data(msg1, ("10.4.0.2", 50000), now=3.0)

        record = registry.get(client_id.hex())
        # With alpha=0.2 and initial EMA=0, first update should be:
        # (1-0.2)*0 + 0.2*50000 = 10000
        expected = _JITTER_EMA_ALPHA * 50000.0
        assert record is not None
        assert abs(record.timing_jitter_us_ema - expected) < 0.01


# ---------------------------------------------------------------------------
# Fix 3: RunStatus constants
# ---------------------------------------------------------------------------


class TestRunStatus:
    """Verify RunStatus constants match database values."""

    @pytest.mark.parametrize(
        ("attr", "expected"),
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


# ---------------------------------------------------------------------------
# Fix 4+5: GitHubAPIClient base class
# ---------------------------------------------------------------------------


class TestGitHubAPIClient:
    """Verify shared base class works for both fetcher types."""

    def test_api_headers_no_token(self) -> None:
        client = GitHubAPIClient()
        headers = client._api_headers()
        assert "Accept" in headers
        assert "Authorization" not in headers

    def test_api_headers_with_token(self) -> None:
        client = GitHubAPIClient()
        client._github_token = "gh-token-123"
        headers = client._api_headers()
        assert headers["Authorization"] == "Bearer gh-token-123"

    def test_server_fetcher_inherits(self) -> None:
        assert issubclass(ServerReleaseFetcher, GitHubAPIClient)

    def test_firmware_fetcher_inherits(self) -> None:
        assert issubclass(GitHubReleaseFetcher, GitHubAPIClient)

    def test_api_get_validates_https(self) -> None:
        client = GitHubAPIClient()
        with pytest.raises(ValueError, match="non-HTTPS"):
            client._api_get("http://insecure.example.com/api")

    def test_server_fetcher_context(self) -> None:
        fetcher = ServerReleaseFetcher(ReleaseFetcherConfig(server_repo="owner/repo"))
        assert fetcher._api_context == "release"

    def test_firmware_fetcher_context(self) -> None:
        fetcher = GitHubReleaseFetcher(FirmwareCacheConfig(cache_dir="/tmp/test"))
        assert fetcher._api_context == "firmware"


# ---------------------------------------------------------------------------
# Fix 6: _client_api_row helper
# ---------------------------------------------------------------------------


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
            ClientSnapshot(name="test-client", connected=False),
        )
        assert set(row.keys()) == _EXPECTED_ROW_KEYS

    def test_connected_row_has_same_keys(self) -> None:
        disconnected = ClientRegistry._client_api_row(
            "aabbccddeeff",
            ClientSnapshot(name="a", connected=False),
        )
        connected = ClientRegistry._client_api_row(
            "aabbccddeeff",
            ClientSnapshot(
                name="b",
                connected=True,
                location="front-left",
                firmware_version="1.0",
                sample_rate_hz=800,
            ),
        )
        assert set(disconnected.keys()) == set(connected.keys())

    def test_defaults_match_old_disconnected_shape(self) -> None:
        """Disconnected client row defaults match the original inline dict."""
        row = ClientRegistry._client_api_row(
            "aabbccddeeff",
            ClientSnapshot(name="test", connected=False),
        )
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
            "aabbccddeeff",
            ClientSnapshot(name="my-sensor", connected=False),
        )
        assert set(rows[0].keys()) == set(helper_row.keys())


# ---------------------------------------------------------------------------
# Fix 7: Shared download chunk constant
# ---------------------------------------------------------------------------


def test_download_chunk_constant() -> None:
    assert DOWNLOAD_CHUNK_BYTES == 1024 * 1024  # 1 MB
    assert DOWNLOAD_CHUNK_BYTES > 0


# ---------------------------------------------------------------------------
# Fix 8: Version comparison warning
# ---------------------------------------------------------------------------


class TestVersionComparisonWarning:
    def test_logs_warning_on_unparseable_version(self) -> None:
        """When packaging cannot parse versions, a warning should be logged
        instead of silently swallowing the exception.
        """
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


# ---------------------------------------------------------------------------
# Fix 9: _cursor type annotation
# ---------------------------------------------------------------------------


def test_cursor_has_return_annotation() -> None:
    """_cursor should have a return type annotation."""
    sig = inspect.signature(HistoryDB._cursor)
    assert sig.return_annotation is not inspect.Parameter.empty


# ---------------------------------------------------------------------------
# Fix 10: BACKUP_SERVER_PORT docstring
# ---------------------------------------------------------------------------


class TestBackupServerPort:
    def test_documented(self) -> None:
        """BACKUP_SERVER_PORT should be 8000 and importable."""
        import importlib
        import os

        os.environ["VIBESENSOR_DISABLE_AUTO_APP"] = "1"
        try:
            mod = importlib.import_module("vibesensor.app")
            assert mod.BACKUP_SERVER_PORT == 8000
        finally:
            os.environ.pop("VIBESENSOR_DISABLE_AUTO_APP", None)
