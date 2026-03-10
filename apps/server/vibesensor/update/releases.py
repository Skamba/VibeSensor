"""Release discovery and download for updater runs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from ..release_fetcher import ReleaseInfo
from .installer import _sha256_file
from .status import UpdateStatusTracker


@dataclass(frozen=True, slots=True)
class UpdateReleaseConfig:
    rollback_dir: Path
    server_repo: str


@dataclass(frozen=True, slots=True)
class UpdateReleaseCheck:
    release: ReleaseInfo | None
    latest_tag: str = ""
    failed: bool = False


class UpdateReleaseService:
    """Checks GitHub releases and downloads the selected wheel."""

    __slots__ = ("_config", "_tracker")

    def __init__(self, *, tracker: UpdateStatusTracker, config: UpdateReleaseConfig) -> None:
        self._tracker = tracker
        self._config = config

    async def check_for_update(self, current_version: str) -> UpdateReleaseCheck:
        from vibesensor.release_fetcher import ReleaseFetcherConfig, ServerReleaseFetcher

        fetcher = ServerReleaseFetcher(
            ReleaseFetcherConfig(
                server_repo=self._config.server_repo,
                rollback_dir=str(self._config.rollback_dir),
            ),
        )
        try:
            release = await asyncio.to_thread(fetcher.check_update_available, current_version)
        except Exception as exc:
            self._tracker.fail("checking", f"Failed to check for updates: {exc}")
            return UpdateReleaseCheck(release=None, failed=True)
        if release is not None:
            return UpdateReleaseCheck(release=release)
        latest_tag = ""
        try:
            latest_release = await asyncio.to_thread(fetcher.find_latest_release)
            if isinstance(latest_release.tag, str):
                latest_tag = latest_release.tag
        except Exception as exc:
            self._tracker.log(
                f"Could not resolve the latest release tag for ESP firmware sync: {exc}",
            )
        return UpdateReleaseCheck(release=None, latest_tag=latest_tag)

    async def download(self, release: ReleaseInfo, staging_dir: Path) -> Path | None:
        from vibesensor.release_fetcher import ReleaseFetcherConfig, ServerReleaseFetcher

        fetcher = ServerReleaseFetcher(
            ReleaseFetcherConfig(
                server_repo=self._config.server_repo,
                rollback_dir=str(self._config.rollback_dir),
            ),
        )
        try:
            return await asyncio.to_thread(fetcher.download_wheel, release, staging_dir)
        except Exception as exc:
            self._tracker.fail("downloading", f"Failed to download release: {exc}")
            return None

    async def verify_download(self, release: ReleaseInfo, wheel_path: Path) -> bool:
        if not release.sha256:
            return True
        actual_sha256 = await asyncio.to_thread(_sha256_file, wheel_path)
        expected_sha256 = release.sha256.lower()
        if actual_sha256 == expected_sha256:
            self._tracker.log(f"SHA-256 verified: {actual_sha256}")
            return True
        self._tracker.fail(
            "downloading",
            "Downloaded wheel SHA-256 mismatch",
            f"expected={release.sha256} actual={actual_sha256}",
        )
        self._tracker.log(f"SHA-256 mismatch: expected {release.sha256} but got {actual_sha256}")
        return False
