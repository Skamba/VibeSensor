"""Release payload shaping and selection helpers for firmware bundle fetching."""

from __future__ import annotations

from collections.abc import Sequence

from vibesensor.use_cases.updates.releases.github_api import (
    GitHubApiAssetRecord,
    GitHubApiReleaseRecord,
)

__all__ = [
    "find_firmware_asset",
    "is_firmware_asset_name",
    "select_firmware_release",
]

_FW_ASSET_PREFIX = "vibesensor-fw-"
_FW_ASSET_SUFFIX = ".zip"


def is_firmware_asset_name(name: str) -> bool:
    """Return True if *name* matches the firmware bundle naming convention."""

    return name.startswith(_FW_ASSET_PREFIX) and name.endswith(_FW_ASSET_SUFFIX)


def _release_has_firmware_asset(release: GitHubApiReleaseRecord) -> bool:
    return any(is_firmware_asset_name(asset.name) for asset in release.assets)


def _preferred_release(
    release: GitHubApiReleaseRecord,
    *,
    wants_prerelease: bool,
) -> bool:
    if release.draft:
        return False
    if not _release_has_firmware_asset(release):
        return False
    return release.prerelease is wants_prerelease


def _fallback_release(release: GitHubApiReleaseRecord) -> bool:
    return not release.draft and _release_has_firmware_asset(release)


def select_firmware_release(
    releases: Sequence[GitHubApiReleaseRecord],
    *,
    channel: str,
    firmware_repo: str,
) -> GitHubApiReleaseRecord:
    """Select the target firmware release for *channel* from the GitHub releases response."""
    wants_prerelease = channel in ("prerelease", "edge")
    for release in releases:
        if _preferred_release(release, wants_prerelease=wants_prerelease):
            return release
    for release in releases:
        if _fallback_release(release):
            return release
    raise ValueError(
        f"No eligible firmware release found for channel '{channel}' in {firmware_repo}",
    )


def find_firmware_asset(release: GitHubApiReleaseRecord) -> GitHubApiAssetRecord:
    """Find the firmware bundle asset in a release."""

    for asset in release.assets:
        if is_firmware_asset_name(asset.name):
            return asset
    raise ValueError(
        f"No firmware bundle asset found in release '{release.tag_name}'. "
        "Expected an asset named vibesensor-fw-*.zip",
    )
