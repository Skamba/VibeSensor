"""Resolve whether an updater run should install a new server release."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.releases import factory as release_fetcher_factory

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.releases.release_fetcher import ReleaseInfo
    from vibesensor.use_cases.updates.status import UpdateStatusTracker

__all__ = [
    "ServerReleaseResolver",
    "UpdateReleaseCheck",
    "UpdateReleaseResolution",
    "check_for_update",
]


@dataclass(frozen=True, slots=True)
class UpdateReleaseCheck:
    """Outcome of checking for a newer server release during updater execution."""

    release: ReleaseInfo | None
    latest_tag: str = ""


@dataclass(frozen=True, slots=True)
class UpdateReleaseResolution:
    """Canonical release-resolution outcome for one updater run."""

    current_version: str
    release: ReleaseInfo | None
    latest_tag: str = ""

    @property
    def update_available(self) -> bool:
        return self.release is not None


class ServerReleaseResolver:
    """Own server release discovery independent from staging or install work."""

    __slots__ = ("_rollback_dir", "_tracker")

    def __init__(self, *, tracker: UpdateStatusTracker, rollback_dir: Path) -> None:
        self._tracker = tracker
        self._rollback_dir = rollback_dir

    async def resolve(self, current_version: str) -> UpdateReleaseResolution:
        release_check = await check_for_update(
            self._tracker,
            self._rollback_dir,
            current_version,
        )
        return UpdateReleaseResolution(
            current_version=current_version,
            release=release_check.release,
            latest_tag=release_check.latest_tag,
        )


async def check_for_update(
    tracker: UpdateStatusTracker,
    rollback_dir: Path,
    current_version: str,
) -> UpdateReleaseCheck:
    """Check GitHub releases for an available update."""

    fetcher = release_fetcher_factory.build_server_release_fetcher(rollback_dir=rollback_dir)
    try:
        release = await asyncio.to_thread(fetcher.check_update_available, current_version)
    except (OSError, ValueError) as exc:
        tracker.fail("checking", f"Failed to check for updates: {exc}")
        raise UpdateReleaseError(f"Failed to check for updates: {exc}") from exc
    if release is not None:
        return UpdateReleaseCheck(release=release)
    latest_tag = ""
    try:
        latest_release = await asyncio.to_thread(fetcher.find_latest_release)
        if isinstance(latest_release.tag, str):
            latest_tag = latest_release.tag
    except (OSError, ValueError) as exc:
        tracker.log(
            f"Could not resolve the latest release tag for ESP firmware sync: {exc}",
        )
    return UpdateReleaseCheck(release=None, latest_tag=latest_tag)
