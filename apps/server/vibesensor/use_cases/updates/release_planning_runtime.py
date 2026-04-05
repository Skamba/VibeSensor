"""Release-planning runtime assembly for updater workflows."""

from __future__ import annotations

from vibesensor.use_cases.updates.release_planner import UpdateReleasePlanner
from vibesensor.use_cases.updates.release_resolution import ServerReleaseResolver
from vibesensor.use_cases.updates.runtime_config import UpdateRuntimeConfig
from vibesensor.use_cases.updates.status import UpdateStatusTracker

__all__ = ["build_update_release_planner"]


def build_update_release_planner(
    *,
    status: UpdateStatusTracker,
    config: UpdateRuntimeConfig,
) -> UpdateReleasePlanner:
    """Build the canonical release planner for one updater workflow."""

    return UpdateReleasePlanner(
        status=status,
        resolver=ServerReleaseResolver(
            rollback_dir=config.rollback_dir,
        ),
    )
