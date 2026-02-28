"""Server release fetcher: download wheel artifacts from GitHub Releases.

Follows the same patterns as :mod:`firmware_cache` for GitHub API access,
HTTPS-only validation, and atomic staging.

Release tag convention: ``server-v<CalVer>``  (e.g. ``server-v2025.6.15``).
Asset pattern: ``vibesensor-*.whl``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

_DEFAULT_REPO = "Skamba/VibeSensor"
_DEFAULT_ROLLBACK_DIR = "/var/lib/vibesensor/rollback"


@dataclass
class ReleaseFetcherConfig:
    """Configuration for fetching server releases from GitHub."""

    server_repo: str = ""
    github_token: str = ""
    rollback_dir: str = ""

    def __post_init__(self) -> None:
        if not self.server_repo:
            self.server_repo = os.environ.get("VIBESENSOR_SERVER_REPO", _DEFAULT_REPO)
        if not self.github_token:
            self.github_token = os.environ.get("GITHUB_TOKEN", "")
        if not self.rollback_dir:
            self.rollback_dir = os.environ.get("VIBESENSOR_ROLLBACK_DIR", _DEFAULT_ROLLBACK_DIR)


@dataclass
class ReleaseInfo:
    """Metadata about a discovered server release."""

    tag: str
    version: str
    asset_name: str
    asset_url: str
    sha256: str = ""
    published_at: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "tag": self.tag,
            "version": self.version,
            "asset_name": self.asset_name,
            "asset_url": self.asset_url,
            "sha256": self.sha256,
            "published_at": self.published_at,
        }


def _validate_url(url: str) -> None:
    if not url.startswith("https://"):
        raise ValueError(f"Refusing non-HTTPS URL for release operation: {url}")


class ServerReleaseFetcher:
    """Fetch server wheel releases from GitHub Releases."""

    def __init__(self, config: ReleaseFetcherConfig | None = None) -> None:
        self._config = config or ReleaseFetcherConfig()

    def _api_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
        if self._config.github_token:
            headers["Authorization"] = f"Bearer {self._config.github_token}"
        return headers

    def _api_get(self, url: str) -> Any:
        _validate_url(url)
        req = Request(url, headers=self._api_headers())
        with urlopen(req, timeout=30) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))

    def _download_asset(self, url: str, dest: Path) -> None:
        _validate_url(url)
        headers = self._api_headers()
        headers["Accept"] = "application/octet-stream"
        req = Request(url, headers=headers)
        with urlopen(req, timeout=300) as resp:  # noqa: S310
            dest.write_bytes(resp.read())

    def find_latest_release(self) -> ReleaseInfo:
        """Find the latest server release (tag matching ``server-v*``).

        Returns :class:`ReleaseInfo` with asset download details.
        Raises ``ValueError`` if no matching release is found.
        """
        owner, repo = self._config.server_repo.split("/", 1)
        url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=50"
        LOGGER.info("Querying releases from %s/%s", owner, repo)
        releases = self._api_get(url)
        if not isinstance(releases, list):
            raise ValueError("Unexpected GitHub API response format")

        for release in releases:
            if release.get("draft", False):
                continue
            tag = release.get("tag_name", "")
            if not tag.startswith("server-v"):
                continue
            version = tag.removeprefix("server-v")
            asset = self._find_wheel_asset(release)
            if asset is None:
                continue
            return ReleaseInfo(
                tag=tag,
                version=version,
                asset_name=asset.get("name", ""),
                asset_url=asset.get("url", ""),
                sha256="",
                published_at=release.get("published_at", ""),
            )

        raise ValueError(
            f"No server release found with tag 'server-v*' in {self._config.server_repo}"
        )

    @staticmethod
    def _find_wheel_asset(release: dict[str, Any]) -> dict[str, Any] | None:
        """Find a .whl asset in a release."""
        for asset in release.get("assets", []):
            name = asset.get("name", "")
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

        sha = hashlib.sha256(dest.read_bytes()).hexdigest()
        release.sha256 = sha
        LOGGER.info("Downloaded %s (sha256=%s)", release.asset_name, sha)
        return dest

    def check_update_available(self, current_version: str) -> ReleaseInfo | None:
        """Check if a newer release is available.

        Returns :class:`ReleaseInfo` if a newer version exists, ``None``
        if already up-to-date or the latest release is older.
        Raises on API errors.
        """
        release = self.find_latest_release()
        if release.version == current_version:
            LOGGER.info("Already up-to-date (version=%s)", current_version)
            return None
        # Guard against suggesting downgrades: compare versions so that only
        # genuinely newer releases are reported.
        try:
            from packaging.version import Version

            if Version(release.version) <= Version(current_version):
                LOGGER.info(
                    "Latest release %s is not newer than current %s; skipping",
                    release.version,
                    current_version,
                )
                return None
        except Exception:
            # If packaging is unavailable or versions are unparseable,
            # fall through and treat any difference as an update.
            pass
        LOGGER.info(
            "Update available: %s → %s",
            current_version,
            release.version,
        )
        return release


def fetch_latest_wheel_cli() -> None:
    """CLI entry point: fetch the latest server release wheel."""
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Fetch the latest VibeSensor server wheel from GitHub Releases"
    )
    parser.add_argument("--repo", default="", help="GitHub owner/repo")
    parser.add_argument("--dest", default=".", help="Destination directory for the wheel")
    args = parser.parse_args()

    config = ReleaseFetcherConfig(server_repo=args.repo)
    fetcher = ServerReleaseFetcher(config)

    try:
        release = fetcher.find_latest_release()
        print(f"Latest release: {release.tag} ({release.version})")
        whl = fetcher.download_wheel(release, dest_dir=args.dest)
        print(f"Downloaded: {whl}")
        print(f"SHA256: {release.sha256}")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
