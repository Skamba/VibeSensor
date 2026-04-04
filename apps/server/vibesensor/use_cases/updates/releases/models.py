"""Typed models and config resolution for server release fetching."""

from __future__ import annotations

import os
from dataclasses import dataclass

from vibesensor.shared.constants.github import GITHUB_REPO
from vibesensor.shared.types.json_types import is_json_array, is_json_object

DEFAULT_RELEASE_FETCHER_ROLLBACK_DIR = "/var/lib/vibesensor/rollback"

__all__ = [
    "DEFAULT_RELEASE_FETCHER_ROLLBACK_DIR",
    "GitHubRelease",
    "GitHubReleaseAsset",
    "ReleaseFetcherConfig",
    "ReleaseInfo",
    "resolve_release_fetcher_config",
]


@dataclass(frozen=True, slots=True)
class ReleaseFetcherConfig:
    """Configuration for fetching server releases from GitHub."""

    server_repo: str = GITHUB_REPO
    github_token: str = ""
    rollback_dir: str = DEFAULT_RELEASE_FETCHER_ROLLBACK_DIR


def resolve_release_fetcher_config(
    *,
    server_repo: str = "",
    github_token: str = "",
    rollback_dir: str = "",
) -> ReleaseFetcherConfig:
    """Resolve runtime defaults for the server release fetcher config."""

    return ReleaseFetcherConfig(
        server_repo=server_repo or os.environ.get("VIBESENSOR_SERVER_REPO", GITHUB_REPO),
        github_token=github_token or os.environ.get("GITHUB_TOKEN", ""),
        rollback_dir=rollback_dir
        or os.environ.get(
            "VIBESENSOR_ROLLBACK_DIR",
            DEFAULT_RELEASE_FETCHER_ROLLBACK_DIR,
        ),
    )


@dataclass
class ReleaseInfo:
    """Metadata about a discovered server release."""

    tag: str
    version: str
    asset_name: str
    asset_url: str
    sha256: str = ""
    published_at: str = ""

    def to_dict(self) -> dict[str, str]:
        """Serialise discovered release metadata for status or debug output."""

        return {
            "tag": self.tag,
            "version": self.version,
            "asset_name": self.asset_name,
            "asset_url": self.asset_url,
            "sha256": self.sha256,
            "published_at": self.published_at,
        }


@dataclass(frozen=True, slots=True)
class GitHubReleaseAsset:
    """Typed GitHub asset row used by the server release fetcher."""

    name: str
    url: str

    @classmethod
    def from_api_payload(cls, raw: object) -> GitHubReleaseAsset | None:
        """Decode one GitHub asset payload into the typed helper model."""

        if not is_json_object(raw):
            return None
        name = raw.get("name")
        url = raw.get("url")
        if not isinstance(name, str) or not isinstance(url, str):
            return None
        return cls(name=name, url=url)


@dataclass(frozen=True, slots=True)
class GitHubRelease:
    """Typed GitHub release row used by the server release fetcher."""

    tag_name: str
    draft: bool
    prerelease: bool
    published_at: str
    assets: tuple[GitHubReleaseAsset, ...]

    @classmethod
    def from_api_payload(cls, raw: object) -> GitHubRelease | None:
        """Decode one GitHub release payload into the typed helper model."""

        if not is_json_object(raw):
            return None
        tag_name = raw.get("tag_name")
        draft = raw.get("draft")
        prerelease = raw.get("prerelease")
        assets_raw = raw.get("assets")
        if (
            not isinstance(tag_name, str)
            or not isinstance(draft, bool)
            or not isinstance(prerelease, bool)
            or not is_json_array(assets_raw)
        ):
            return None
        published_at_raw = raw.get("published_at")
        assets: list[GitHubReleaseAsset] = []
        for item in assets_raw:
            asset = GitHubReleaseAsset.from_api_payload(item)
            if asset is None:
                return None
            assets.append(asset)
        return cls(
            tag_name=tag_name,
            draft=draft,
            prerelease=prerelease,
            published_at=published_at_raw if isinstance(published_at_raw, str) else "",
            assets=tuple(assets),
        )
