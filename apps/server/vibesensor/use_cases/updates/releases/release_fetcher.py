"""Server release fetcher for wheel artifacts from GitHub Releases."""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from pathlib import Path
from urllib.request import urlopen

from vibesensor.shared.types.json_types import is_json_array

from .github_api import DOWNLOAD_CHUNK_BYTES, GitHubApiClient
from .models import GitHubRelease, GitHubReleaseAsset, ReleaseFetcherConfig, ReleaseInfo

LOGGER = logging.getLogger(__name__)

_HASH_CHUNK_BYTES = 65536  # 64 KB per hash update

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

        req = self._client.build_request(url, accept="application/octet-stream")
        tmp = dest.with_suffix(".tmp")
        max_bytes = self._MAX_DOWNLOAD_BYTES
        chunk_size = DOWNLOAD_CHUNK_BYTES
        replaced = False
        try:
            with urlopen(req, timeout=300) as resp:
                total = 0
                with tmp.open("wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            raise ValueError(f"Asset exceeds {self._MAX_DOWNLOAD_MB} MB limit")
                        f.write(chunk)
                    f.flush()
                    os.fsync(f.fileno())
            tmp.replace(dest)
            replaced = True
        finally:
            if not replaced:
                tmp.unlink(missing_ok=True)

    def find_latest_release(self) -> ReleaseInfo:
        """Find the latest server release (tag matching ``server-v*``).

        Returns :class:`ReleaseInfo` with asset download details.
        Raises ``ValueError`` if no matching release is found.
        """
        owner, repo = self._config.server_repo.split("/", 1)
        url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=50"
        LOGGER.info("Querying releases from %s/%s", owner, repo)
        releases_raw = self._client.get_json(url)
        if not is_json_array(releases_raw):
            raise ValueError("Unexpected GitHub API response format")
        releases: list[GitHubRelease] = []
        for item in releases_raw:
            release = GitHubRelease.from_api_payload(item)
            if release is None:
                raise ValueError("Unexpected GitHub API response format")
            releases.append(release)

        for release in releases:
            if release.draft:
                continue
            tag = release.tag_name
            if not tag.startswith("server-v"):
                continue
            version = tag.removeprefix("server-v")
            asset = self._find_wheel_asset(release)
            if asset is None:
                continue
            return ReleaseInfo(
                tag=tag,
                version=version,
                asset_name=asset.name,
                asset_url=asset.url,
                sha256="",
                published_at=release.published_at,
            )

        raise ValueError(
            f"No server release found with tag 'server-v*' in {self._config.server_repo}",
        )

    @staticmethod
    def _find_wheel_asset(release: GitHubRelease) -> GitHubReleaseAsset | None:
        """Find a .whl asset in a release."""
        for asset in release.assets:
            name = asset.name
            if name.startswith("vibesensor") and name.endswith(".whl"):
                return asset
        return None

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

        h = hashlib.sha256()
        with dest.open("rb") as f:
            for chunk in iter(lambda: f.read(_HASH_CHUNK_BYTES), b""):
                h.update(chunk)
        sha = h.hexdigest()
        release.sha256 = sha
        LOGGER.info("Downloaded %s (sha256=%s)", release.asset_name, sha)
        return dest
