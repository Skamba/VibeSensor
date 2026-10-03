"""Stage and verify update release artifacts (wheel + dependency wheelhouse) before install."""

from __future__ import annotations

import asyncio
import shutil
import tarfile
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from vibesensor.common.exceptions import UpdateCleanupError, UpdateReleaseError
from vibesensor.updates.artifact_validation import sha256_file
from vibesensor.updates.models import UpdatePhase

if TYPE_CHECKING:
    from vibesensor.updates.releases.release_fetcher import (
        ReleaseInfo,
        ServerReleaseFetcher,
    )
    from vibesensor.updates.status.tracker import UpdateStatusTracker

_DOWNLOADING = UpdatePhase.downloading.value


@dataclass(frozen=True, slots=True)
class StagedServerRelease:
    """Downloaded and verified release, ready to install offline."""

    release: ReleaseInfo
    wheel_path: Path
    wheelhouse_dir: Path


def extract_wheelhouse(archive: Path, dest: Path) -> Path:
    """Unpack a wheelhouse tar that may only contain top-level ``.whl`` files."""
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        for member in members:
            name = member.name
            flat_wheel = "/" not in name and not name.startswith(".") and name.endswith(".whl")
            if not (member.isfile() and flat_wheel):
                raise ValueError(f"unexpected wheelhouse entry {name!r}")
        if not members:
            raise ValueError("wheelhouse is empty")
        dest.mkdir(parents=True)
        tar.extractall(dest, members=members, filter="data")
    return dest


class ServerReleaseStager:
    """Own temporary staging, download, and verification of release artifacts.

    Staging lives under *staging_parent* (the venv root, on the SD card) rather
    than ``/tmp``, which is RAM-backed on Raspberry Pi OS.
    """

    __slots__ = ("_release_fetcher", "_staging_parent", "_status")

    def __init__(
        self,
        *,
        status: UpdateStatusTracker,
        release_fetcher: ServerReleaseFetcher,
        staging_parent: Path,
    ) -> None:
        self._status = status
        self._release_fetcher = release_fetcher
        self._staging_parent = staging_parent

    @asynccontextmanager
    async def stage(self, release: ReleaseInfo) -> AsyncIterator[StagedServerRelease]:
        self._status.transition(UpdatePhase.downloading)
        if not release.wheelhouse_name:
            raise UpdateReleaseError(
                f"Release {release.tag} has no dependency wheelhouse",
                phase=_DOWNLOADING,
            )
        self._status.log(f"Downloading release {release.tag}...")
        for stale in self._staging_parent.glob(".staging-*"):
            shutil.rmtree(stale, ignore_errors=True)  # left by an interrupted update
        try:
            staging_dir = Path(tempfile.mkdtemp(prefix=".staging-", dir=self._staging_parent))
        except OSError as exc:
            raise UpdateReleaseError(
                "Could not create the release staging directory",
                phase=_DOWNLOADING,
                detail=str(exc),
            ) from exc
        prior_error: BaseException | None = None
        try:
            try:
                wheel_path = await self._download(
                    release.asset_name, release.asset_url, release.sha256, staging_dir
                )
                archive = await self._download(
                    release.wheelhouse_name,
                    release.wheelhouse_url,
                    release.wheelhouse_sha256,
                    staging_dir,
                )
                wheelhouse_dir = await self._extract(archive, staging_dir / "wheelhouse")
                yield StagedServerRelease(
                    release=release,
                    wheel_path=wheel_path,
                    wheelhouse_dir=wheelhouse_dir,
                )
            except BaseException as exc:
                prior_error = exc
                raise
        finally:
            self._cleanup_staging_dir(staging_dir, prior_error=prior_error)

    def _cleanup_staging_dir(
        self,
        staging_dir: Path,
        *,
        prior_error: BaseException | None,
    ) -> None:
        try:
            shutil.rmtree(staging_dir)
        except OSError as exc:
            cleanup_error = UpdateCleanupError(
                f"Failed to remove staged release directory: {exc}",
                phase="cleanup",
            )
            if prior_error is not None:
                prior_error.add_note(str(cleanup_error))
                return
            raise cleanup_error from exc

    async def _download(self, name: str, url: str, sha256: str, staging_dir: Path) -> Path:
        """Download one asset and verify it against its trusted GitHub SHA-256 digest."""
        if not sha256:
            raise UpdateReleaseError(
                "Release asset is missing a trusted SHA-256 digest",
                phase=_DOWNLOADING,
                detail=name,
            )
        try:
            path = await asyncio.to_thread(
                self._release_fetcher.download_asset,
                name,
                url,
                staging_dir,
            )
        except (OSError, ValueError) as exc:
            raise UpdateReleaseError(
                f"Failed to download {name}: {exc}",
                phase=_DOWNLOADING,
            ) from exc
        actual_sha256 = await asyncio.to_thread(sha256_file, path)
        if actual_sha256 != sha256.lower():
            raise UpdateReleaseError(
                f"Downloaded {name} SHA-256 mismatch",
                phase=_DOWNLOADING,
                detail=f"expected={sha256} actual={actual_sha256}",
                log_message=f"SHA-256 mismatch: expected {sha256} but got {actual_sha256}",
            )
        self._status.log(f"Downloaded {name} (SHA-256 verified: {actual_sha256})")
        return path

    async def _extract(self, archive: Path, dest: Path) -> Path:
        try:
            wheelhouse_dir = await asyncio.to_thread(extract_wheelhouse, archive, dest)
        except (OSError, ValueError, tarfile.TarError) as exc:
            raise UpdateReleaseError(
                "Downloaded wheelhouse is invalid",
                phase=_DOWNLOADING,
                detail=f"{archive.name}: {exc}",
            ) from exc
        archive.unlink()
        return wheelhouse_dir
