"""Release discovery and download for updater runs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from vibesensor.use_cases.updates.installer import _sha256_file
from vibesensor.use_cases.updates.release_fetcher import ReleaseInfo
from vibesensor.use_cases.updates.status import UpdateStatusTracker


@dataclass(frozen=True, slots=True)
class UpdateReleaseCheck:
    release: ReleaseInfo | None
    latest_tag: str = ""
    failed: bool = False


async def check_for_update(
    tracker: UpdateStatusTracker,
    rollback_dir: Path,
    current_version: str,
) -> UpdateReleaseCheck:
    """Check GitHub releases for an available update."""
    from vibesensor.use_cases.updates.release_fetcher import ReleaseFetcherConfig, ServerReleaseFetcher

    fetcher = ServerReleaseFetcher(
        ReleaseFetcherConfig(rollback_dir=str(rollback_dir)),
    )
    try:
        release = await asyncio.to_thread(fetcher.check_update_available, current_version)
    except Exception as exc:
        tracker.fail("checking", f"Failed to check for updates: {exc}")
        return UpdateReleaseCheck(release=None, failed=True)
    if release is not None:
        return UpdateReleaseCheck(release=release)
    latest_tag = ""
    try:
        latest_release = await asyncio.to_thread(fetcher.find_latest_release)
        if isinstance(latest_release.tag, str):
            latest_tag = latest_release.tag
    except Exception as exc:
        tracker.log(
            f"Could not resolve the latest release tag for ESP firmware sync: {exc}",
        )
    return UpdateReleaseCheck(release=None, latest_tag=latest_tag)


async def download_release(
    tracker: UpdateStatusTracker,
    rollback_dir: Path,
    release: ReleaseInfo,
    staging_dir: Path,
) -> Path | None:
    """Download a release wheel to *staging_dir*."""
    from vibesensor.use_cases.updates.release_fetcher import ReleaseFetcherConfig, ServerReleaseFetcher

    fetcher = ServerReleaseFetcher(
        ReleaseFetcherConfig(rollback_dir=str(rollback_dir)),
    )
    try:
        return await asyncio.to_thread(fetcher.download_wheel, release, staging_dir)
    except Exception as exc:
        tracker.fail("downloading", f"Failed to download release: {exc}")
        return None


async def verify_download(
    tracker: UpdateStatusTracker,
    release: ReleaseInfo,
    wheel_path: Path,
) -> bool:
    """Verify SHA-256 digest of a downloaded wheel."""
    if not release.sha256:
        return True
    actual_sha256 = await asyncio.to_thread(_sha256_file, wheel_path)
    expected_sha256 = release.sha256.lower()
    if actual_sha256 == expected_sha256:
        tracker.log(f"SHA-256 verified: {actual_sha256}")
        return True
    tracker.fail(
        "downloading",
        "Downloaded wheel SHA-256 mismatch",
        f"expected={release.sha256} actual={actual_sha256}",
    )
    tracker.log(f"SHA-256 mismatch: expected {release.sha256} but got {actual_sha256}")
    return False
