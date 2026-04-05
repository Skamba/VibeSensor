"""Release payload shaping and selection helpers for firmware bundle fetching."""

from __future__ import annotations

from vibesensor.shared.types.json_types import JsonObject, is_json_array, is_json_object
from vibesensor.use_cases.updates.firmware.firmware_types import (
    GitHubReleaseAssetPayload,
    GitHubReleasePayload,
)

__all__ = [
    "find_firmware_asset",
    "is_firmware_asset_name",
    "require_release_payload",
    "select_firmware_release",
]

_FW_ASSET_PREFIX = "vibesensor-fw-"
_FW_ASSET_SUFFIX = ".zip"


def _coerce_release_asset_payload(raw: JsonObject) -> GitHubReleaseAssetPayload:
    """Project a raw GitHub asset JSON object into the updater payload shape."""

    payload: GitHubReleaseAssetPayload = {}
    name = raw.get("name")
    url = raw.get("url")
    if isinstance(name, str):
        payload["name"] = name
    if isinstance(url, str):
        payload["url"] = url
    return payload


def _coerce_release_payload(raw: JsonObject) -> GitHubReleasePayload:
    """Project a raw GitHub release JSON object into the updater payload shape."""

    payload: GitHubReleasePayload = {}
    tag_name = raw.get("tag_name")
    if isinstance(tag_name, str):
        payload["tag_name"] = tag_name
    draft = raw.get("draft")
    if isinstance(draft, bool):
        payload["draft"] = draft
    prerelease = raw.get("prerelease")
    if isinstance(prerelease, bool):
        payload["prerelease"] = prerelease
    assets = raw.get("assets")
    if is_json_array(assets):
        payload["assets"] = [
            _coerce_release_asset_payload(asset) for asset in assets if is_json_object(asset)
        ]
    return payload


def is_firmware_asset_name(name: str) -> bool:
    """Return True if *name* matches the firmware bundle naming convention."""

    return name.startswith(_FW_ASSET_PREFIX) and name.endswith(_FW_ASSET_SUFFIX)


def require_release_payload(raw: object) -> GitHubReleasePayload:
    """Decode one GitHub release response into the firmware payload shape."""

    if not is_json_object(raw):
        raise ValueError("Unexpected GitHub API response format")
    return _coerce_release_payload(raw)


def _release_has_firmware_asset(release: GitHubReleasePayload) -> bool:
    return any(is_firmware_asset_name(str(a.get("name", ""))) for a in release.get("assets", []))


def _preferred_release(
    release: GitHubReleasePayload,
    *,
    wants_prerelease: bool,
) -> bool:
    if release.get("draft", False):
        return False
    if not _release_has_firmware_asset(release):
        return False
    return bool(release.get("prerelease", False)) is wants_prerelease


def _fallback_release(release: GitHubReleasePayload) -> bool:
    return not release.get("draft", False) and _release_has_firmware_asset(release)


def select_firmware_release(
    releases_raw: object,
    *,
    channel: str,
    firmware_repo: str,
) -> GitHubReleasePayload:
    """Select the target firmware release for *channel* from the GitHub releases response."""

    if not is_json_array(releases_raw):
        raise ValueError("Unexpected GitHub API response format")
    releases = [
        _coerce_release_payload(release) for release in releases_raw if is_json_object(release)
    ]
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


def find_firmware_asset(release: GitHubReleasePayload) -> GitHubReleaseAssetPayload:
    """Find the firmware bundle asset in a release."""

    for asset in release.get("assets", []):
        if is_firmware_asset_name(str(asset.get("name", ""))):
            return asset
    raise ValueError(
        f"No firmware bundle asset found in release '{release.get('tag_name', '?')}'. "
        "Expected an asset named vibesensor-fw-*.zip",
    )
