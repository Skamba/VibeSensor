"""Resolve whether an updater run should install a new server release."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from vibesensor.use_cases.updates.releases import check_for_update

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.releases.release_fetcher import ReleaseInfo
    from vibesensor.use_cases.updates.status import UpdateStatusTracker


@dataclass(frozen=True, slots=True)
class UpdateReleaseResolution:
    """Canonical release-resolution outcome for one updater run."""

    current_version: str
    release: ReleaseInfo | None
    latest_tag: str = ""
    failed: bool = False

    @property
    def update_available(self) -> bool:
        return self.release is not None and not self.failed


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
            failed=release_check.failed,
        )
