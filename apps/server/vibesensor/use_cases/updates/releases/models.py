"""Typed models and config resolution for server release fetching."""

from __future__ import annotations

import string
from dataclasses import dataclass

from vibesensor.shared.constants.github import GITHUB_REPO
from vibesensor.use_cases.updates.releases.github_api import (
    GitHubApiAssetRecord,
    GitHubApiReleaseRecord,
)

__all__ = [
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


def resolve_release_fetcher_config(
    *,
    server_repo: str = "",
    github_token: str = "",
) -> ReleaseFetcherConfig:
    """Resolve runtime defaults for the server release fetcher config."""
    from vibesensor.shared.process_settings import load_update_env_settings

    env_settings = load_update_env_settings()
    return ReleaseFetcherConfig(
        server_repo=server_repo or env_settings.server_repo,
        github_token=github_token or env_settings.github_token,
    )


@dataclass(frozen=True, slots=True)
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
    sha256: str = ""

    @classmethod
    def from_api_record(cls, raw: GitHubApiAssetRecord) -> GitHubReleaseAsset:
        """Project one typed GitHub API asset record into the helper model."""

        return cls(
            name=raw.name,
            url=raw.url,
            sha256=_parse_asset_digest(raw.digest),
        )


@dataclass(frozen=True, slots=True)
class GitHubRelease:
    """Typed GitHub release row used by the server release fetcher."""

    tag_name: str
    draft: bool
    prerelease: bool
    published_at: str
    assets: tuple[GitHubReleaseAsset, ...]

    @classmethod
    def from_api_record(cls, raw: GitHubApiReleaseRecord) -> GitHubRelease:
        """Project one typed GitHub API release record into the helper model."""

        return cls(
            tag_name=raw.tag_name,
            draft=raw.draft,
            prerelease=raw.prerelease,
            published_at=raw.published_at,
            assets=tuple(GitHubReleaseAsset.from_api_record(item) for item in raw.assets),
        )


def _parse_asset_digest(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    if not raw.startswith("sha256:"):
        return ""
    sha256 = raw.removeprefix("sha256:").strip().lower()
    if len(sha256) != 64:
        return ""
    if any(ch not in string.hexdigits for ch in sha256):
        return ""
    return sha256
