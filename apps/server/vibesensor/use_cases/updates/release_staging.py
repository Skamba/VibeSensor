"""Stage and verify update release artifacts before deployment."""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateReleaseError
from vibesensor.use_cases.updates.artifact_validation import sha256_file
from vibesensor.use_cases.updates.models import UpdatePhase
from vibesensor.use_cases.updates.releases import factory as release_fetcher_factory

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.releases.release_fetcher import ReleaseInfo
    from vibesensor.use_cases.updates.status import UpdateStatusTracker


@dataclass(frozen=True, slots=True)
class StagedServerRelease:
    """Downloaded and verified wheel artifact ready for deployment."""

    release: ReleaseInfo
    wheel_path: Path


class ServerReleaseStager:
    """Own temporary staging, download, and verification of server wheels."""

    __slots__ = ("_rollback_dir", "_tracker")

    def __init__(self, *, tracker: UpdateStatusTracker, rollback_dir: Path) -> None:
        self._tracker = tracker
        self._rollback_dir = rollback_dir

    @asynccontextmanager
    async def stage(self, release: ReleaseInfo) -> AsyncIterator[StagedServerRelease]:
        self._tracker.transition(UpdatePhase.downloading)
        self._tracker.log(f"Downloading release {release.tag}...")
        staging_dir = Path(tempfile.mkdtemp(prefix="vibesensor-update-"))
        try:
            wheel_path = await download_release(
                self._tracker,
                self._rollback_dir,
                release,
                staging_dir,
            )
            self._tracker.log(
                f"Downloaded {wheel_path.name} (sha256={getattr(release, 'sha256', '')})",
            )
            await verify_download(self._tracker, release, wheel_path)
            yield StagedServerRelease(release=release, wheel_path=wheel_path)
        finally:
            active_error = sys.exc_info()[1]
            try:
                shutil.rmtree(staging_dir)
            except OSError as exc:
                cleanup_error = UpdateCleanupError(
                    f"Failed to remove staged release directory: {exc}",
                )
                if active_error is not None:
                    active_error.add_note(str(cleanup_error))
                else:
                    raise cleanup_error from exc


async def download_release(
    tracker: UpdateStatusTracker,
    rollback_dir: Path,
    release: ReleaseInfo,
    staging_dir: Path,
) -> Path:
    """Download a release wheel to *staging_dir*."""

    fetcher = release_fetcher_factory.build_server_release_fetcher(rollback_dir=rollback_dir)
    try:
        return await asyncio.to_thread(fetcher.download_wheel, release, staging_dir)
    except (OSError, ValueError) as exc:
        tracker.fail("downloading", f"Failed to download release: {exc}")
        raise UpdateReleaseError(f"Failed to download release: {exc}") from exc


async def verify_download(
    tracker: UpdateStatusTracker,
    release: ReleaseInfo,
    wheel_path: Path,
) -> None:
    """Verify SHA-256 digest of a downloaded wheel."""

    if not release.sha256:
        return
    actual_sha256 = await asyncio.to_thread(sha256_file, wheel_path)
    expected_sha256 = release.sha256.lower()
    if actual_sha256 == expected_sha256:
        tracker.log(f"SHA-256 verified: {actual_sha256}")
        return
    tracker.fail(
        "downloading",
        "Downloaded wheel SHA-256 mismatch",
        f"expected={release.sha256} actual={actual_sha256}",
    )
    tracker.log(f"SHA-256 mismatch: expected {release.sha256} but got {actual_sha256}")
    raise UpdateReleaseError("Downloaded wheel SHA-256 mismatch")
