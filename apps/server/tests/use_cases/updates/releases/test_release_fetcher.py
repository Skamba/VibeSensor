"""Tests for updater server release helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vibesensor.use_cases.updates.releases.github_api import (
    GitHubApiAssetRecord,
    GitHubApiClient,
    GitHubApiReleaseRecord,
    validate_https_url,
)
from vibesensor.use_cases.updates.releases.models import (
    GitHubRelease,
    GitHubReleaseAsset,
    ReleaseFetcherConfig,
    ReleaseInfo,
    resolve_release_fetcher_config,
)
from vibesensor.use_cases.updates.releases.release_fetcher import ServerReleaseFetcher
from vibesensor.use_cases.updates.releases.version_policy import select_update_release


def _asset_record(
    *,
    name: str,
    url: str,
    digest: str = "",
) -> GitHubApiAssetRecord:
    return GitHubApiAssetRecord(name=name, url=url, digest=digest)


def _release_record(
    *,
    tag_name: str,
    draft: bool,
    prerelease: bool,
    assets: list[GitHubApiAssetRecord],
    published_at: str = "",
) -> GitHubApiReleaseRecord:
    return GitHubApiReleaseRecord(
        tag_name=tag_name,
        draft=draft,
        prerelease=prerelease,
        published_at=published_at,
        assets=assets,
    )


class TestValidateUrl:
    def test_https_accepted(self) -> None:
        validate_https_url("https://api.github.com/repos/owner/repo")

    @pytest.mark.parametrize(
        "url",
        [
            "http://example.com/release.whl",
            "ftp://example.com/release.whl",
        ],
        ids=["http", "ftp"],
    )
    def test_non_https_rejected(self, url: str) -> None:
        with pytest.raises(ValueError, match="non-HTTPS"):
            validate_https_url(url)


class TestReleaseFetcherConfig:
    def test_defaults(self) -> None:
        config = ReleaseFetcherConfig()
        assert config.server_repo == "Skamba/VibeSensor"
        assert config.github_token == ""

    def test_resolve_uses_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIBESENSOR_SERVER_REPO", "test/repo")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")

        config = resolve_release_fetcher_config()

        assert config.server_repo == "test/repo"
        assert config.github_token == "ghp_test123"

    def test_resolve_prefers_explicit_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIBESENSOR_SERVER_REPO", "env/repo")

        config = resolve_release_fetcher_config(server_repo="explicit/repo")

        assert config.server_repo == "explicit/repo"


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

        assert info.to_dict() == {
            "tag": "server-v2025.6.15",
            "version": "2025.6.15",
            "asset_name": "vibesensor-2025.6.15-py3-none-any.whl",
            "asset_url": "https://api.github.com/repos/Skamba/VibeSensor/releases/assets/123",
            "sha256": "abc123",
            "published_at": "2025-06-15T02:00:00Z",
        }


class TestGitHubReleaseAsset:
    def test_from_api_record_projects_required_fields(self) -> None:
        assert GitHubReleaseAsset.from_api_record(
            _asset_record(name="wheel.whl", url="https://a")
        ) == (GitHubReleaseAsset(name="wheel.whl", url="https://a", sha256=""))

    def test_from_api_record_parses_sha256_digest(self) -> None:
        asset = GitHubReleaseAsset.from_api_record(
            _asset_record(
                name="wheel.whl",
                url="https://a",
                digest=f"sha256:{'a' * 64}",
            )
        )

        assert asset == GitHubReleaseAsset(
            name="wheel.whl",
            url="https://a",
            sha256="a" * 64,
        )


class TestGitHubRelease:
    def test_from_api_record_decodes_release(self) -> None:
        release = GitHubRelease.from_api_record(
            _release_record(
                tag_name="server-v2025.6.15",
                draft=False,
                prerelease=False,
                published_at="2025-06-15T02:00:00Z",
                assets=[
                    _asset_record(
                        name="vibesensor-2025.6.15-py3-none-any.whl",
                        url="https://a",
                        digest=f"sha256:{'a' * 64}",
                    )
                ],
            )
        )

        assert release == GitHubRelease(
            tag_name="server-v2025.6.15",
            draft=False,
            prerelease=False,
            published_at="2025-06-15T02:00:00Z",
            assets=(
                GitHubReleaseAsset(
                    name="vibesensor-2025.6.15-py3-none-any.whl",
                    url="https://a",
                    sha256="a" * 64,
                ),
            ),
        )


class TestGitHubApiClient:
    def test_api_headers_without_token(self) -> None:
        headers = GitHubApiClient().api_headers()

        assert "Authorization" not in headers
        assert headers["Accept"] == "application/vnd.github+json"

    def test_api_headers_with_token(self) -> None:
        headers = GitHubApiClient(token="ghp_test").api_headers()

        assert headers["Authorization"] == "Bearer ghp_test"


MOCK_RELEASES = [
    _release_record(
        tag_name="fw-v2025.6.14",
        draft=False,
        prerelease=False,
        published_at="2025-06-14T02:30:00Z",
        assets=[
            _asset_record(
                name="vibesensor-fw-v2025.6.14.zip", url="https://api.github.com/fw-asset"
            )
        ],
    ),
    _release_record(
        tag_name="server-v2025.6.15",
        draft=False,
        prerelease=False,
        published_at="2025-06-15T02:00:00Z",
        assets=[
            _asset_record(
                name="vibesensor-2025.6.15-py3-none-any.whl",
                url="https://api.github.com/assets/456",
                digest=f"sha256:{'a' * 64}",
            )
        ],
    ),
    _release_record(
        tag_name="server-v2025.6.14",
        draft=False,
        prerelease=False,
        published_at="2025-06-14T02:00:00Z",
        assets=[
            _asset_record(
                name="vibesensor-2025.6.14-py3-none-any.whl",
                url="https://api.github.com/assets/123",
                digest=f"sha256:{'b' * 64}",
            )
        ],
    ),
]


class TestServerReleaseFetcher:
    def _make_fetcher(
        self,
        *,
        client: GitHubApiClient | None = None,
    ) -> ServerReleaseFetcher:
        return ServerReleaseFetcher(
            ReleaseFetcherConfig(server_repo="Skamba/VibeSensor"),
            client=client,
        )

    def test_find_latest_release(self) -> None:
        client = MagicMock(spec=GitHubApiClient)
        client.get_typed_json.return_value = MOCK_RELEASES
        fetcher = self._make_fetcher(client=client)
        release = fetcher.find_latest_release()

        assert release.tag == "server-v2025.6.15"
        assert release.version == "2025.6.15"
        assert release.asset_name == "vibesensor-2025.6.15-py3-none-any.whl"
        assert release.sha256 == "a" * 64

    def test_find_latest_skips_draft(self) -> None:
        releases = [
            _release_record(
                tag_name="server-v2025.6.16",
                draft=True,
                prerelease=False,
                assets=[
                    _asset_record(name="vibesensor-2025.6.16-py3-none-any.whl", url="https://a")
                ],
            ),
            *MOCK_RELEASES,
        ]
        client = MagicMock(spec=GitHubApiClient)
        client.get_typed_json.return_value = releases
        fetcher = self._make_fetcher(client=client)
        release = fetcher.find_latest_release()

        assert release.tag == "server-v2025.6.15"

    def test_find_latest_surfaces_typed_decode_failures(self) -> None:
        client = MagicMock(spec=GitHubApiClient)
        client.get_typed_json.side_effect = ValueError("Unexpected GitHub API response format")
        fetcher = self._make_fetcher(client=client)

        with pytest.raises(ValueError, match="Unexpected GitHub API response format"):
            fetcher.find_latest_release()

    @pytest.mark.parametrize(
        "releases",
        [
            pytest.param(
                [
                    _release_record(
                        tag_name="fw-v2025.6.15",
                        draft=False,
                        prerelease=False,
                        assets=[
                            _asset_record(name="vibesensor-fw-v2025.6.15.zip", url="https://a")
                        ],
                    ),
                ],
                id="firmware-only-tags",
            ),
            pytest.param([], id="empty-releases"),
        ],
    )
    def test_find_latest_no_server_release(self, releases: list[GitHubApiReleaseRecord]) -> None:
        client = MagicMock(spec=GitHubApiClient)
        client.get_typed_json.return_value = releases
        fetcher = self._make_fetcher(client=client)

        with pytest.raises(ValueError, match="No server release found"):
            fetcher.find_latest_release()

    def test_find_latest_surfaces_non_array_api_response(self) -> None:
        client = MagicMock(spec=GitHubApiClient)
        client.get_typed_json.side_effect = ValueError("Unexpected GitHub API response format")
        fetcher = self._make_fetcher(client=client)

        with pytest.raises(ValueError, match="Unexpected GitHub API response format"):
            fetcher.find_latest_release()

    def test_find_latest_rejects_release_without_trusted_digest(self) -> None:
        client = MagicMock(spec=GitHubApiClient)
        client.get_typed_json.return_value = [
            _release_record(
                tag_name="server-v2025.6.15",
                draft=False,
                prerelease=False,
                assets=[
                    _asset_record(
                        name="vibesensor-2025.6.15-py3-none-any.whl",
                        url="https://api.github.com/assets/456",
                    )
                ],
            ),
        ]
        fetcher = self._make_fetcher(client=client)

        with pytest.raises(ValueError, match="missing a trusted SHA-256 digest"):
            fetcher.find_latest_release()

    def test_download_wheel(self, tmp_path: Path) -> None:
        release = ReleaseInfo(
            tag="server-v2025.6.15",
            version="2025.6.15",
            asset_name="vibesensor-2025.6.15-py3-none-any.whl",
            asset_url="https://api.github.com/assets/456",
            sha256="a" * 64,
        )
        wheel_content = b"fake-wheel-content"

        class _DownloadFetcher(ServerReleaseFetcher):
            def _download_asset(self, url: str, dest: Path) -> None:
                del url
                dest.write_bytes(wheel_content)

        fetcher = _DownloadFetcher(ReleaseFetcherConfig(server_repo="Skamba/VibeSensor"))
        path = fetcher.download_wheel(release, dest_dir=tmp_path)

        assert path.exists()
        assert path.name == "vibesensor-2025.6.15-py3-none-any.whl"
        assert path.read_bytes() == wheel_content
        assert release.sha256 == "a" * 64


class TestVersionPolicy:
    def test_select_update_release_returns_newer_release(self) -> None:
        release = ReleaseInfo(
            tag="server-v2025.6.15",
            version="2025.6.15",
            asset_name="vibesensor-2025.6.15-py3-none-any.whl",
            asset_url="https://api.github.com/assets/456",
        )

        assert (
            select_update_release(
                current_version="2025.6.14",
                latest_release=release,
            )
            is release
        )

    def test_select_update_release_skips_matching_version(self) -> None:
        release = ReleaseInfo(
            tag="server-v2025.6.15",
            version="2025.6.15",
            asset_name="vibesensor-2025.6.15-py3-none-any.whl",
            asset_url="https://api.github.com/assets/456",
        )

        assert (
            select_update_release(
                current_version="2025.6.15",
                latest_release=release,
            )
            is None
        )

    def test_select_update_release_logs_warning_on_unparseable_version(self) -> None:
        release = ReleaseInfo(
            tag="server-v!!!INVALID!!!",
            version="!!!INVALID!!!",
            asset_name="vibesensor-0.0.0-py3-none-any.whl",
            asset_url="https://api.github.com/repos/owner/repo/releases/assets/1",
        )

        with patch("vibesensor.use_cases.updates.releases.version_policy.LOGGER") as mock_logger:
            result = select_update_release(
                current_version="1.0.0",
                latest_release=release,
            )

        assert result is release
        mock_logger.warning.assert_called_once()
        assert "Could not compare versions" in mock_logger.warning.call_args[0][0]
