"""GitHub release discovery and download for firmware bundles."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

from vibesensor.use_cases.updates.asset_download import download_release_asset
from vibesensor.use_cases.updates.firmware.firmware_release_selection import (
    find_firmware_asset,
    is_firmware_asset_name,
    select_firmware_release,
)
from vibesensor.use_cases.updates.firmware.firmware_types import FirmwareCacheConfig
from vibesensor.use_cases.updates.releases.github_api import (
    DOWNLOAD_CHUNK_BYTES,
    GitHubApiAssetRecord,
    GitHubApiClient,
    GitHubApiReleaseRecord,
)

LOGGER = logging.getLogger(__name__)

__all__ = [
    "GitHubApiAssetRecord",
    "GitHubReleaseFetcher",
    "GitHubApiReleaseRecord",
    "is_firmware_asset_name",
]

_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024  # 100 MB hard limit for firmware assets


class GitHubReleaseFetcher:
    """Fetch firmware bundles from GitHub Releases."""

    __slots__ = ("_client", "_config")

    def __init__(
        self,
        config: FirmwareCacheConfig,
        *,
        client: GitHubApiClient | None = None,
    ) -> None:
        self._config = config
        self._client = client or GitHubApiClient(
            token=config.github_token,
            context="firmware",
        )

    def _download_asset(self, url: str, dest: Path) -> None:
        download_release_asset(
            client=self._client,
            url=url,
            dest=dest,
            timeout_s=120,
            max_bytes=_MAX_DOWNLOAD_BYTES,
            chunk_size=DOWNLOAD_CHUNK_BYTES,
            size_limit_message=(
                f"Firmware asset exceeds {_MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB "
                "size limit; aborting download to prevent OOM."
            ),
        )

    def find_release(self) -> GitHubApiReleaseRecord:
        """Find the target release based on config (pinned tag, channel)."""
        owner, repo = self._config.firmware_repo.split("/", 1)
        base = f"https://api.github.com/repos/{owner}/{repo}/releases"

        if self._config.pinned_tag:
            url = f"{base}/tags/{self._config.pinned_tag}"
            LOGGER.info("Fetching pinned release: %s", self._config.pinned_tag)
            return cast(
                GitHubApiReleaseRecord,
                self._client.get_typed_json(
                    url,
                    response_type=GitHubApiReleaseRecord,
                ),
            )

        LOGGER.info("Fetching releases for channel '%s'", self._config.channel)
        return select_firmware_release(
            cast(
                list[GitHubApiReleaseRecord],
                self._client.get_typed_json(
                    f"{base}?per_page=50",
                    response_type=list[GitHubApiReleaseRecord],
                ),
            ),
            channel=self._config.channel,
            firmware_repo=self._config.firmware_repo,
        )

    def find_firmware_asset(self, release: GitHubApiReleaseRecord) -> GitHubApiAssetRecord:
        """Find the firmware bundle asset in a release."""
        return find_firmware_asset(release)

    def download_asset(self, asset: GitHubApiAssetRecord, dest: Path) -> Path:
        """Download a firmware asset zip to *dest*."""
        asset_url = asset.url
        asset_name = asset.name or dest.name or "bundle.zip"
        dest.parent.mkdir(parents=True, exist_ok=True)
        LOGGER.info("Downloading firmware asset: %s", asset_name)
        self._download_asset(asset_url, dest)
        return dest
