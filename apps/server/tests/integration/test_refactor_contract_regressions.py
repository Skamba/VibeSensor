"""Cross-module refactor-contract regressions.

Validates that the refactored code preserves behaviour while being more
maintainable than the originals.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from vibesensor.adapters.persistence.history_db import (
    HistoryPersistenceAdapters,
    create_history_persistence_adapters,
)
from vibesensor.adapters.udp.protocol import DataMessage, HelloMessage
from vibesensor.domain import RunStatus
from vibesensor.infra.runtime.client_snapshot import ClientSnapshot
from vibesensor.infra.runtime.registry import ClientRegistry
from vibesensor.infra.runtime.registry_updates import _JITTER_EMA_ALPHA, _RESTART_SEQ_GAP
from vibesensor.shared.boundaries.clients import build_client_api_row, snapshot_for_api
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.updates.firmware.firmware_release_fetcher import GitHubReleaseFetcher
from vibesensor.use_cases.updates.firmware.firmware_types import FirmwareCacheConfig
from vibesensor.use_cases.updates.releases.github_api import GitHubApiClient
from vibesensor.use_cases.updates.releases.models import ReleaseFetcherConfig, ReleaseInfo
from vibesensor.use_cases.updates.releases.release_fetcher import ServerReleaseFetcher
from vibesensor.use_cases.updates.releases.version_policy import select_update_release

# ---------------------------------------------------------------------------
# Shared constants / fixtures
# ---------------------------------------------------------------------------

_CLIENT_ID = bytes.fromhex("aabbccddeeff")


def _metadata(run_id: str, **overrides: object) -> RunMetadata:
    payload: dict[str, object] = {
        "run_id": run_id,
        "start_time_utc": "2024-01-01T00:00:00Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 1.0,
    }
    payload.update(overrides)
    return run_metadata_from_mapping(payload)


_SAMPLES_200X3 = np.zeros((200, 3), dtype=np.int16)


@pytest.fixture
def db(tmp_path: Path) -> HistoryPersistenceAdapters:
    return create_history_persistence_adapters(tmp_path / "history.db")


@pytest.fixture
def registry(db: HistoryPersistenceAdapters) -> ClientRegistry:
    return ClientRegistry(db=db.client_name_repository)


def _hello(client_id: bytes = _CLIENT_ID, **overrides: object) -> HelloMessage:
    defaults: dict[str, object] = {
        "client_id": client_id,
        "control_port": 9010,
        "sample_rate_hz": 800,
        "name": "node-1",
        "firmware_version": "fw",
    }
    defaults.update(overrides)
    return HelloMessage(**defaults)


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

    def test_history_db_uses_run_status(self, db: HistoryPersistenceAdapters) -> None:
        """delete_run_if_safe should return RunStatus.ANALYZING for analyzing runs."""
        db.run_repository.create_run("run-1", "2024-01-01T00:00:00Z", _metadata("run-1"))
        db.run_repository.finalize_run("run-1", "2024-01-01T00:01:00Z")
        deleted, reason = db.run_repository.delete_run_if_safe("run-1")
        assert not deleted
        assert reason == RunStatus.ANALYZING


# ---------------------------------------------------------------------------
# Fix 4+5: shared GitHub API client composition
# ---------------------------------------------------------------------------


class TestGitHubApiClient:
    """Verify both updater fetchers share the same GitHub API client surface."""

    def test_api_headers_no_token(self) -> None:
        client = GitHubApiClient()
        headers = client.api_headers()
        assert "Accept" in headers
        assert "Authorization" not in headers

    def test_api_headers_with_token(self) -> None:
        client = GitHubApiClient(token="gh-token-123")
        headers = client.api_headers()
        assert headers["Authorization"] == "Bearer gh-token-123"

    def test_build_request_validates_https(self) -> None:
        client = GitHubApiClient()
        with pytest.raises(ValueError, match="non-HTTPS"):
            client.build_request("http://insecure.example.com/api")

    def test_server_fetcher_context(self) -> None:
        client = GitHubApiClient(context="release")
        fetcher = ServerReleaseFetcher(
            ReleaseFetcherConfig(server_repo="owner/repo"),
            client=client,
        )
        assert fetcher._client.context == "release"

    def test_firmware_fetcher_context(self) -> None:
        client = GitHubApiClient(context="firmware")
        fetcher = GitHubReleaseFetcher(
            FirmwareCacheConfig(cache_dir="/tmp/test"),
            client=client,
        )
        assert fetcher._client.context == "firmware"


# ---------------------------------------------------------------------------
# Fix 6: client snapshot presenter helper
# ---------------------------------------------------------------------------


_EXPECTED_ROW_KEYS = {
    "id",
    "mac_address",
    "name",
    "connected",
    "location_code",
    "firmware_version",
    "sample_rate_hz",
    "frame_samples",
    "last_seen_age_ms",
    "frames_total",
    "dropped_frames",
    "latest_metrics",
    "reset_count",
    "last_reset_time",
}


class TestClientApiRow:
    """Verify the extracted client snapshot presenter produces correct dicts."""

    def test_disconnected_row_has_all_keys(self) -> None:
        row = build_client_api_row(
            ClientSnapshot(client_id="aabbccddeeff", name="test-client", connected=False),
        )
        assert set(row.keys()) == _EXPECTED_ROW_KEYS

    def test_connected_row_has_same_keys(self) -> None:
        disconnected = build_client_api_row(
            ClientSnapshot(client_id="aabbccddeeff", name="a", connected=False),
        )
        connected = build_client_api_row(
            ClientSnapshot(
                client_id="aabbccddeeff",
                name="b",
                connected=True,
                location_code="front-left",
                firmware_version="1.0",
                sample_rate_hz=800,
            ),
        )
        assert set(disconnected.keys()) == set(connected.keys())

    def test_defaults_match_old_disconnected_shape(self) -> None:
        """Disconnected client row defaults match the original inline dict."""
        row = build_client_api_row(
            ClientSnapshot(client_id="aabbccddeeff", name="test", connected=False),
        )
        assert row["connected"] is False
        assert row["location_code"] == ""
        assert row["firmware_version"] == ""
        assert row["sample_rate_hz"] == 0
        assert row["frames_total"] == 0
        assert row["latest_metrics"] == {}

    def test_snapshot_uses_helper(self, registry: ClientRegistry) -> None:
        """Verify snapshot_for_api returns rows with the same keys as build_client_api_row."""
        registry.set_name("aabbccddeeff", "my-sensor")
        rows = snapshot_for_api(registry, now=1.0, now_mono=1.0)
        assert len(rows) == 1
        helper_row = build_client_api_row(
            ClientSnapshot(client_id="aabbccddeeff", name="my-sensor", connected=False),
        )
        assert set(rows[0].keys()) == set(helper_row.keys())

    def test_lightweight_row_keeps_frame_samples_without_metrics(self) -> None:
        row = build_client_api_row(
            ClientSnapshot(
                client_id="aabbccddeeff",
                name="sensor",
                connected=True,
                sample_rate_hz=400,
                frame_samples=200,
            ),
            include_metrics=False,
        )
        assert row["frame_samples"] == 200
        assert "latest_metrics" not in row


# ---------------------------------------------------------------------------
# Fix 8: Version comparison warning
# ---------------------------------------------------------------------------


class TestVersionComparisonWarning:
    def test_logs_warning_on_unparseable_version(self) -> None:
        """When packaging cannot parse versions, a warning should be logged
        instead of silently swallowing the exception.
        """
        fake_release = ReleaseInfo(
            tag="server-v!!!INVALID!!!",
            version="!!!INVALID!!!",
            asset_name="vibesensor-0.0.0-py3-none-any.whl",
            asset_url="https://api.github.com/repos/owner/repo/releases/assets/1",
        )

        with patch("vibesensor.use_cases.updates.releases.version_policy.LOGGER") as mock_logger:
            result = select_update_release(
                current_version="1.0.0",
                latest_release=fake_release,
            )

        # Should still return the release (treating unparseable as update)
        assert result is not None
        # Should have logged a warning
        mock_logger.warning.assert_called_once()
        assert "Could not compare versions" in mock_logger.warning.call_args[0][0]
