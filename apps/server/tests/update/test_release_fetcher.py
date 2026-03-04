"""Tests for release_fetcher module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from vibesensor.release_fetcher import (
    ReleaseFetcherConfig,
    ReleaseInfo,
    ServerReleaseFetcher,
    validate_https_url,
)

# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


class TestValidateUrl:
    def test_https_accepted(self) -> None:
        validate_https_url("https://api.github.com/repos/owner/repo")

    def test_http_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-HTTPS"):
            validate_https_url("http://example.com/release.whl")

    def test_ftp_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-HTTPS"):
            validate_https_url("ftp://example.com/release.whl")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestReleaseFetcherConfig:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VIBESENSOR_SERVER_REPO", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("VIBESENSOR_ROLLBACK_DIR", raising=False)
        config = ReleaseFetcherConfig()
        assert config.server_repo == "Skamba/VibeSensor"
        assert config.github_token == ""
        assert config.rollback_dir == "/var/lib/vibesensor/rollback"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIBESENSOR_SERVER_REPO", "test/repo")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        monkeypatch.setenv("VIBESENSOR_ROLLBACK_DIR", "/tmp/rollback")
        config = ReleaseFetcherConfig()
        assert config.server_repo == "test/repo"
        assert config.github_token == "ghp_test123"
        assert config.rollback_dir == "/tmp/rollback"

    def test_explicit_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIBESENSOR_SERVER_REPO", "env/repo")
        config = ReleaseFetcherConfig(server_repo="explicit/repo")
        assert config.server_repo == "explicit/repo"


# ---------------------------------------------------------------------------
# ReleaseInfo
# ---------------------------------------------------------------------------


class TestReleaseInfo:
    def test_to_dict(self) -> None:
        info = ReleaseInfo(
            tag="server-v2025.6.15",
            version="2025.6.15",
            asset_name="vibesensor-2025.6.15-py3-none-any.whl",
            asset_url="https://api.github.com/repos/Skamba/VibeSensor/releases/assets/123",
            sha256="abc123",
            published_at="2025-06-15T02:00:00Z",
        )
        d = info.to_dict()
        assert d["tag"] == "server-v2025.6.15"
        assert d["version"] == "2025.6.15"
        assert d["sha256"] == "abc123"


# ---------------------------------------------------------------------------
# ServerReleaseFetcher
# ---------------------------------------------------------------------------

MOCK_RELEASES = [
    {
        "tag_name": "fw-v2025.6.14",
        "draft": False,
        "prerelease": False,
        "published_at": "2025-06-14T02:30:00Z",
        "assets": [
            {"name": "vibesensor-fw-v2025.6.14.zip", "url": "https://api.github.com/fw-asset"},
        ],
    },
    {
        "tag_name": "server-v2025.6.15",
        "draft": False,
        "prerelease": False,
        "published_at": "2025-06-15T02:00:00Z",
        "assets": [
            {
                "name": "vibesensor-2025.6.15-py3-none-any.whl",
                "url": "https://api.github.com/assets/456",
            },
        ],
    },
    {
        "tag_name": "server-v2025.6.14",
        "draft": False,
        "prerelease": False,
        "published_at": "2025-06-14T02:00:00Z",
        "assets": [
            {
                "name": "vibesensor-2025.6.14-py3-none-any.whl",
                "url": "https://api.github.com/assets/123",
            },
        ],
    },
]


class TestServerReleaseFetcher:
    def _make_fetcher(self) -> ServerReleaseFetcher:
        config = ReleaseFetcherConfig(server_repo="Skamba/VibeSensor")
        return ServerReleaseFetcher(config)

    def test_find_latest_release(self) -> None:
        fetcher = self._make_fetcher()
        with patch.object(fetcher, "_api_get", return_value=MOCK_RELEASES):
            release = fetcher.find_latest_release()
        assert release.tag == "server-v2025.6.15"
        assert release.version == "2025.6.15"
        assert release.asset_name == "vibesensor-2025.6.15-py3-none-any.whl"

    def test_find_latest_skips_draft(self) -> None:
        releases = [
            {
                "tag_name": "server-v2025.6.16",
                "draft": True,
                "prerelease": False,
                "assets": [
                    {"name": "vibesensor-2025.6.16-py3-none-any.whl", "url": "https://a"},
                ],
            },
            *MOCK_RELEASES,
        ]
        fetcher = self._make_fetcher()
        with patch.object(fetcher, "_api_get", return_value=releases):
            release = fetcher.find_latest_release()
        assert release.tag == "server-v2025.6.15"

    def test_find_latest_skips_firmware_tags(self) -> None:
        releases = [
            {
                "tag_name": "fw-v2025.6.15",
                "draft": False,
                "prerelease": False,
                "assets": [{"name": "vibesensor-fw-v2025.6.15.zip", "url": "https://a"}],
            },
        ]
        fetcher = self._make_fetcher()
        with patch.object(fetcher, "_api_get", return_value=releases):
            with pytest.raises(ValueError, match="No server release found"):
                fetcher.find_latest_release()

    def test_find_latest_no_releases(self) -> None:
        fetcher = self._make_fetcher()
        with patch.object(fetcher, "_api_get", return_value=[]):
            with pytest.raises(ValueError, match="No server release found"):
                fetcher.find_latest_release()

    def test_check_update_available_newer(self) -> None:
        fetcher = self._make_fetcher()
        with patch.object(fetcher, "_api_get", return_value=MOCK_RELEASES):
            result = fetcher.check_update_available("2025.6.14")
        assert result is not None
        assert result.version == "2025.6.15"

    def test_check_update_available_up_to_date(self) -> None:
        fetcher = self._make_fetcher()
        with patch.object(fetcher, "_api_get", return_value=MOCK_RELEASES):
            result = fetcher.check_update_available("2025.6.15")
        assert result is None

    def test_download_wheel(self, tmp_path: Path) -> None:
        fetcher = self._make_fetcher()
        release = ReleaseInfo(
            tag="server-v2025.6.15",
            version="2025.6.15",
            asset_name="vibesensor-2025.6.15-py3-none-any.whl",
            asset_url="https://api.github.com/assets/456",
        )
        wheel_content = b"fake-wheel-content"
        with patch.object(fetcher, "_download_asset") as mock_dl:
            mock_dl.side_effect = lambda url, dest: dest.write_bytes(wheel_content)
            path = fetcher.download_wheel(release, dest_dir=tmp_path)
        assert path.exists()
        assert path.name == "vibesensor-2025.6.15-py3-none-any.whl"
        assert path.read_bytes() == wheel_content
        assert release.sha256  # Should be populated after download

    def test_api_headers_without_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        config = ReleaseFetcherConfig(server_repo="a/b", github_token="")
        fetcher = ServerReleaseFetcher(config)
        headers = fetcher._api_headers()
        assert "Authorization" not in headers
        assert headers["Accept"] == "application/vnd.github+json"

    def test_api_headers_with_token(self) -> None:
        config = ReleaseFetcherConfig(server_repo="a/b", github_token="ghp_test")
        fetcher = ServerReleaseFetcher(config)
        headers = fetcher._api_headers()
        assert headers["Authorization"] == "Bearer ghp_test"
