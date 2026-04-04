"""Shared construction boundary for updater release fetchers."""

from __future__ import annotations

from pathlib import Path

from vibesensor.use_cases.updates.releases.models import resolve_release_fetcher_config
from vibesensor.use_cases.updates.releases.release_fetcher import ServerReleaseFetcher

__all__ = ["build_server_release_fetcher"]


def build_server_release_fetcher(*, rollback_dir: Path) -> ServerReleaseFetcher:
    """Create the canonical server-release fetcher for one updater run."""

    return ServerReleaseFetcher(
        resolve_release_fetcher_config(rollback_dir=str(rollback_dir)),
    )
