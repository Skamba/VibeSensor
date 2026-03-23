"""GitHub release discovery and download for firmware bundles."""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

from vibesensor.shared.types.json_types import JsonObject, is_json_array, is_json_object
from vibesensor.use_cases.updates.firmware.firmware_types import (
    FirmwareCacheConfig,
    GitHubReleaseAssetPayload,
    GitHubReleasePayload,
)
from vibesensor.use_cases.updates.releases.release_fetcher import (
    DOWNLOAD_CHUNK_BYTES,
    GitHubAPIClient,
    validate_https_url,
)

LOGGER = logging.getLogger(__name__)

__all__ = [
    "GitHubReleaseAssetPayload",
    "GitHubReleaseFetcher",
    "GitHubReleasePayload",
    "is_firmware_asset_name",
]

_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024  # 100 MB hard limit for firmware assets
_FW_ASSET_PREFIX = "vibesensor-fw-"
_FW_ASSET_SUFFIX = ".zip"


def _coerce_release_asset_payload(raw: JsonObject) -> GitHubReleaseAssetPayload:
    payload: GitHubReleaseAssetPayload = {}
    name = raw.get("name")
    url = raw.get("url")
    if isinstance(name, str):
        payload["name"] = name
    if isinstance(url, str):
        payload["url"] = url
    return payload


def _coerce_release_payload(raw: JsonObject) -> GitHubReleasePayload:
    payload: GitHubReleasePayload = {}
    tag_name = raw.get("tag_name")
    if isinstance(tag_name, str):
        payload["tag_name"] = tag_name
    draft = raw.get("draft")
    if isinstance(draft, bool):
        payload["draft"] = draft
    prerelease = raw.get("prerelease")
    if isinstance(prerelease, bool):
        payload["prerelease"] = prerelease
    assets = raw.get("assets")
    if is_json_array(assets):
        payload["assets"] = [
            _coerce_release_asset_payload(asset) for asset in assets if is_json_object(asset)
        ]
    return payload


def is_firmware_asset_name(name: str) -> bool:
    """Return True if *name* matches the firmware bundle naming convention."""
    return name.startswith(_FW_ASSET_PREFIX) and name.endswith(_FW_ASSET_SUFFIX)


class GitHubReleaseFetcher(GitHubAPIClient):
    """Fetch firmware bundles from GitHub Releases."""

    def __init__(self, config: FirmwareCacheConfig) -> None:
        self._config = config
        self._github_token = config.github_token
        self._api_context = "firmware"

    def _download_asset(self, url: str, dest: Path) -> None:
        validate_https_url(url, context="firmware")
        headers = self._api_headers()
        headers["Accept"] = "application/octet-stream"
        req = Request(url, headers=headers)
        with urlopen(req, timeout=120) as resp:
            # Stream directly to a temp file to avoid buffering the entire
            # firmware binary in memory (Pi 3A+ has only 512 MB RAM).
            tmp_fd, tmp_path = tempfile.mkstemp(dir=str(dest.parent), suffix=".dl_tmp")
            fdopen_ok = False
            try:
                total = 0
                with os.fdopen(tmp_fd, "wb") as tmp_f:
                    fdopen_ok = True
                    while True:
                        chunk = resp.read(DOWNLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > _MAX_DOWNLOAD_BYTES:
                            raise ValueError(
                                f"Firmware asset exceeds {_MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB "
                                f"size limit; aborting download to prevent OOM.",
                            )
                        tmp_f.write(chunk)
                Path(tmp_path).replace(dest)
            except BaseException:
                # If os.fdopen() failed, the raw fd is still open; close it.
                # Once os.fdopen() succeeds it owns the fd (closed by `with`).
                if not fdopen_ok:
                    with contextlib.suppress(OSError):
                        os.close(tmp_fd)
                # Clean up partial temp file on any failure
                with contextlib.suppress(OSError):
                    Path(tmp_path).unlink()
                raise

    def find_release(self) -> GitHubReleasePayload:
        """Find the target release based on config (pinned tag, channel)."""
        owner, repo = self._config.firmware_repo.split("/", 1)
        base = f"https://api.github.com/repos/{owner}/{repo}/releases"

        if self._config.pinned_tag:
            url = f"{base}/tags/{self._config.pinned_tag}"
            LOGGER.info("Fetching pinned release: %s", self._config.pinned_tag)
            release = self._api_get(url)
            if not is_json_object(release):
                raise ValueError("Unexpected GitHub API response format")
            return _coerce_release_payload(release)

        LOGGER.info("Fetching releases for channel '%s'", self._config.channel)
        releases = self._api_get(f"{base}?per_page=50")
        if not isinstance(releases, list):
            raise ValueError("Unexpected GitHub API response format")

        for release in releases:
            if not is_json_object(release):
                continue
            is_prerelease = release.get("prerelease", False)
            is_draft = release.get("draft", False)
            if is_draft:
                continue
            release_payload = _coerce_release_payload(release)
            if not self._release_has_firmware_asset(release_payload):
                continue
            if self._config.channel == "stable" and not is_prerelease:
                return release_payload
            if self._config.channel in ("prerelease", "edge") and is_prerelease:
                return release_payload

        # Fallback: use the latest prerelease (firmware releases are typically prereleases)
        for release in releases:
            if not is_json_object(release):
                continue
            if release.get("draft", False):
                continue
            release_payload = _coerce_release_payload(release)
            if not self._release_has_firmware_asset(release_payload):
                continue
            return release_payload

        raise ValueError(
            f"No eligible firmware release found for channel '{self._config.channel}' "
            f"in {self._config.firmware_repo}",
        )

    @staticmethod
    def _release_has_firmware_asset(release: GitHubReleasePayload) -> bool:
        return any(
            is_firmware_asset_name(str(a.get("name", ""))) for a in release.get("assets", [])
        )

    def find_firmware_asset(self, release: GitHubReleasePayload) -> GitHubReleaseAssetPayload:
        """Find the firmware bundle asset in a release."""
        for asset in release.get("assets", []):
            if is_firmware_asset_name(str(asset.get("name", ""))):
                return asset
        raise ValueError(
            f"No firmware bundle asset found in release '{release.get('tag_name', '?')}'. "
            "Expected an asset named vibesensor-fw-*.zip",
        )

    def download_asset(self, asset: GitHubReleaseAssetPayload, dest: Path) -> Path:
        """Download a firmware asset zip to *dest*."""
        asset_url = str(asset.get("url", ""))
        asset_name = str(asset.get("name", dest.name or "bundle.zip"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        LOGGER.info("Downloading firmware asset: %s", asset_name)
        self._download_asset(asset_url, dest)
        return dest
