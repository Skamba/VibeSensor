"""Cross-module refactor-contract regressions.

Validates that the refactored code preserves behaviour while being more
maintainable than the originals.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vibesensor.firmware_cache import FirmwareCacheConfig, GitHubReleaseFetcher
from vibesensor.history_db import HistoryDB
from vibesensor.protocol import HelloMessage
from vibesensor.registry import (
    ClientRegistry,
)
from vibesensor.release_fetcher import (
    GitHubAPIClient,
    ReleaseFetcherConfig,
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
