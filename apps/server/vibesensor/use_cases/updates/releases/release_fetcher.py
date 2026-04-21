"""Server release fetcher for wheel artifacts from GitHub Releases."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import cast

from vibesensor.use_cases.updates.asset_download import download_release_asset

from .github_api import DOWNLOAD_CHUNK_BYTES, GitHubApiClient, GitHubApiReleaseRecord
from .models import ReleaseFetcherConfig, ReleaseInfo
from .release_discovery import decode_server_releases, find_latest_server_release

LOGGER = logging.getLogger(__name__)

__all__ = ["ServerReleaseFetcher"]


class ServerReleaseFetcher:
    """Fetch server wheel releases from GitHub Releases."""

    __slots__ = ("_client", "_config")

    def __init__(
        self,
        config: ReleaseFetcherConfig,
        *,
        client: GitHubApiClient | None = None,
    ) -> None:
        self._config = config
        self._client = client or GitHubApiClient(
            token=config.github_token,
            context="release",
        )

    _MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024  # 200 MB hard limit
    _MAX_DOWNLOAD_MB = _MAX_DOWNLOAD_BYTES // (1024 * 1024)

    def _download_asset(self, url: str, dest: Path) -> None:
        """Stream a release asset to disk with an upper size bound."""

        download_release_asset(
            client=self._client,
            url=url,
            dest=dest,
            timeout_s=300,
            max_bytes=self._MAX_DOWNLOAD_BYTES,
            chunk_size=DOWNLOAD_CHUNK_BYTES,
            size_limit_message=f"Asset exceeds {self._MAX_DOWNLOAD_MB} MB limit",
            temp_suffix=".whl_tmp",
        )

    def find_latest_release(self) -> ReleaseInfo:
        """Find the latest server release (tag matching ``server-v*``).

        Returns :class:`ReleaseInfo` with asset download details.
        Raises ``ValueError`` if no matching release is found.
        """
        owner, repo = self._config.server_repo.split("/", 1)
        url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=50"
        LOGGER.info("Querying releases from %s/%s", owner, repo)
        return find_latest_server_release(
            decode_server_releases(
                cast(
                    list[GitHubApiReleaseRecord],
                    self._client.get_typed_json(
                        url,
                        response_type=list[GitHubApiReleaseRecord],
                    ),
                )
            ),
            server_repo=self._config.server_repo,
        )

    def download_wheel(
        self,
        release: ReleaseInfo,
        dest_dir: str | Path | None = None,
    ) -> Path:
        """Download the wheel for a release.

        Returns the path to the downloaded ``.whl`` file.
        """
        if dest_dir is None:
            dest_dir = Path(tempfile.mkdtemp(prefix="vibesensor-release-"))
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest = dest_dir / release.asset_name
        LOGGER.info("Downloading %s", release.asset_name)
        self._download_asset(release.asset_url, dest)
        LOGGER.info("Downloaded %s", release.asset_name)
        return dest
