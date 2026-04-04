"""Version-selection policy for discovered server releases."""

from __future__ import annotations

import logging

from packaging.version import Version

from .models import ReleaseInfo

LOGGER = logging.getLogger(__name__)

__all__ = ["select_update_release"]


def select_update_release(
    *,
    current_version: str,
    latest_release: ReleaseInfo,
) -> ReleaseInfo | None:
    """Return *latest_release* only when it is newer than *current_version*."""

    if latest_release.version == current_version:
        return None
    try:
        if Version(latest_release.version) <= Version(current_version):
            LOGGER.info(
                "Latest release %s is not newer than current %s; skipping",
                latest_release.version,
                current_version,
            )
            return None
    except ValueError:
        LOGGER.warning(
            "Could not compare versions %r vs %r; treating as update",
            latest_release.version,
            current_version,
            exc_info=True,
        )
    return latest_release
