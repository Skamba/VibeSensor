"""Resolve whether an updater run should install a new server release."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.releases import factory as release_fetcher_factory

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.releases.release_fetcher import (
        ReleaseInfo,
        ServerReleaseFetcher,
    )
    from vibesensor.use_cases.updates.status import UpdateStatusController, UpdateStatusRecorder

__all__ = ["ServerReleaseResolver", "UpdateReleaseResolution"]


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

    __slots__ = ("_rollback_dir", "_status_controller", "_status_recorder")

    def __init__(
        self,
        *,
        status_controller: UpdateStatusController,
        status_recorder: UpdateStatusRecorder,
        rollback_dir: Path,
    ) -> None:
        self._status_controller = status_controller
        self._status_recorder = status_recorder
        self._rollback_dir = rollback_dir

    async def resolve(self, current_version: str) -> UpdateReleaseResolution:
        fetcher = release_fetcher_factory.build_server_release_fetcher(
            rollback_dir=self._rollback_dir,
        )
        release = await self._check_for_update(fetcher, current_version)
        if release is None:
            return UpdateReleaseResolution(
                current_version=current_version,
                release=None,
                latest_tag=await self._latest_tag(fetcher),
            )
        return UpdateReleaseResolution(
            current_version=current_version,
            release=release,
        )

    async def _check_for_update(
        self,
        fetcher: ServerReleaseFetcher,
        current_version: str,
    ) -> ReleaseInfo | None:
        try:
            return await asyncio.to_thread(fetcher.check_update_available, current_version)
        except (OSError, ValueError) as exc:
            self._status_recorder.add_issue("checking", f"Failed to check for updates: {exc}")
            self._status_controller.mark_failed()
            raise UpdateReleaseError(f"Failed to check for updates: {exc}") from exc

    async def _latest_tag(self, fetcher: ServerReleaseFetcher) -> str:
        try:
            latest_release = await asyncio.to_thread(fetcher.find_latest_release)
        except (OSError, ValueError) as exc:
            self._status_recorder.log(
                f"Could not resolve the latest release tag for ESP firmware sync: {exc}",
            )
            return ""
        return latest_release.tag if isinstance(latest_release.tag, str) else ""
