"""Server release discovery helpers for updater fetchers."""

from __future__ import annotations

from collections.abc import Iterable

from .github_api import GitHubApiReleaseRecord
from .models import GitHubRelease, GitHubReleaseAsset, ReleaseInfo

__all__ = [
    "decode_server_releases",
    "find_latest_server_release",
    "find_server_wheel_asset",
]


def decode_server_releases(releases: Iterable[GitHubApiReleaseRecord]) -> tuple[GitHubRelease, ...]:
    """Project typed GitHub API release records into server-release rows."""

    return tuple(GitHubRelease.from_api_record(item) for item in releases)


def find_server_wheel_asset(release: GitHubRelease) -> GitHubReleaseAsset | None:
    """Return the server wheel asset for *release* when present."""

    for asset in release.assets:
        if asset.name.startswith("vibesensor") and asset.name.endswith(".whl"):
            return asset
    return None


def find_latest_server_release(
    releases: Iterable[GitHubRelease],
    *,
    server_repo: str,
) -> ReleaseInfo:
    """Select the first eligible server release from decoded GitHub rows."""

    for release in releases:
        if release.draft:
            continue
        tag = release.tag_name
        if not tag.startswith("server-v"):
            continue
        asset = find_server_wheel_asset(release)
        if asset is None:
            continue
        if not asset.sha256:
            raise ValueError(
                f"Server release {tag} is missing a trusted SHA-256 digest for {asset.name}",
            )
        return ReleaseInfo(
            tag=tag,
            version=tag.removeprefix("server-v"),
            asset_name=asset.name,
            asset_url=asset.url,
            sha256=asset.sha256,
            published_at=release.published_at,
        )
    raise ValueError(
        f"No server release found with tag 'server-v*' in {server_repo}",
    )
