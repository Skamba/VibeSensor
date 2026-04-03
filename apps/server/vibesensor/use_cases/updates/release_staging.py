"""Stage and verify update release artifacts before deployment."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

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
    async def stage(self, release: ReleaseInfo) -> AsyncIterator[StagedServerRelease | None]:
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
            if wheel_path is None:
                yield None
                return
            self._tracker.log(
                f"Downloaded {wheel_path.name} (sha256={getattr(release, 'sha256', '')})",
            )
            if not await verify_download(self._tracker, release, wheel_path):
                yield None
                return
            yield StagedServerRelease(release=release, wheel_path=wheel_path)
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)


async def download_release(
    tracker: UpdateStatusTracker,
    rollback_dir: Path,
    release: ReleaseInfo,
    staging_dir: Path,
) -> Path | None:
    """Download a release wheel to *staging_dir*."""

    fetcher = release_fetcher_factory.build_server_release_fetcher(rollback_dir=rollback_dir)
    try:
        return await asyncio.to_thread(fetcher.download_wheel, release, staging_dir)
    except (OSError, ValueError) as exc:
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
    actual_sha256 = await asyncio.to_thread(sha256_file, wheel_path)
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
