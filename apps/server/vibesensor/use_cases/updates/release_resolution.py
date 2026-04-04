"""Resolve whether an updater run should install a new server release."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.releases import factory as release_fetcher_factory
from vibesensor.use_cases.updates.releases.version_policy import select_update_release

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.releases.release_fetcher import (
        ReleaseInfo,
        ServerReleaseFetcher,
    )

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

    __slots__ = ("_rollback_dir",)

    def __init__(
        self,
        *,
        rollback_dir: Path,
    ) -> None:
        self._rollback_dir = rollback_dir

    async def resolve(self, current_version: str) -> UpdateReleaseResolution:
        fetcher = release_fetcher_factory.build_server_release_fetcher(
            rollback_dir=self._rollback_dir,
        )
        latest_release = await self._find_latest_release(fetcher)
        release = select_update_release(
            current_version=current_version,
            latest_release=latest_release,
        )
        if release is None:
            return UpdateReleaseResolution(
                current_version=current_version,
                release=None,
                latest_tag=latest_release.tag,
            )
        return UpdateReleaseResolution(
            current_version=current_version,
            release=release,
        )

    async def _find_latest_release(
        self,
        fetcher: ServerReleaseFetcher,
    ) -> ReleaseInfo:
        try:
            return await asyncio.to_thread(fetcher.find_latest_release)
        except (OSError, ValueError) as exc:
            raise UpdateReleaseError(
                f"Failed to check for updates: {exc}",
                phase="checking",
            ) from exc
