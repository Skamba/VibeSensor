"""Shared construction boundary for updater release fetchers."""

from __future__ import annotations

from pathlib import Path

from vibesensor.use_cases.updates.releases import release_fetcher

__all__ = ["build_server_release_fetcher"]


def build_server_release_fetcher(*, rollback_dir: Path) -> release_fetcher.ServerReleaseFetcher:
    """Create the canonical server-release fetcher for one updater run."""

    return release_fetcher.ServerReleaseFetcher(
        release_fetcher.ReleaseFetcherConfig(rollback_dir=str(rollback_dir)),
    )
