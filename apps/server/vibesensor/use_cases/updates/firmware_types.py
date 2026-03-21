from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TypedDict

from vibesensor.shared.constants import GITHUB_REPO

__all__ = [
    "BundleMeta",
    "FirmwareCacheConfig",
    "FirmwareCacheInfoPayload",
    "FlashManifest",
    "GitHubReleaseAssetPayload",
    "GitHubReleasePayload",
    "ManifestEnvironment",
    "ManifestEnvironmentPayload",
    "ManifestSegment",
    "ManifestSegmentPayload",
]

_DEFAULT_CACHE_DIR = "/var/lib/vibesensor/firmware"


class ManifestSegmentPayload(TypedDict, total=False):
    file: str
    offset: str
    sha256: str


class ManifestEnvironmentPayload(TypedDict, total=False):
    name: str
    segments: list[ManifestSegmentPayload]


class GitHubReleaseAssetPayload(TypedDict, total=False):
    name: str
    url: str


class GitHubReleasePayload(TypedDict, total=False):
    tag_name: str
    draft: bool
    prerelease: bool
    assets: list[GitHubReleaseAssetPayload]


class FirmwareCacheInfoPayload(TypedDict, total=False):
    status: str
    message: str
    source: str
    tag: str
    asset: str
    timestamp: str
    sha256: str
    cache_dir: str
    bundle_path: str


@dataclass
class FirmwareCacheConfig:
    """Configuration for the local ESP32 firmware download cache."""

    cache_dir: str = ""
    firmware_repo: str = GITHUB_REPO
    channel: str = "stable"  # "stable" or "prerelease"
    pinned_tag: str = ""
    github_token: str = ""

    def __post_init__(self) -> None:
        if not self.cache_dir:
            self.cache_dir = os.environ.get("VIBESENSOR_FIRMWARE_CACHE_DIR", _DEFAULT_CACHE_DIR)
        if not self.firmware_repo:
            self.firmware_repo = os.environ.get("VIBESENSOR_FIRMWARE_REPO", GITHUB_REPO)
        if not self.channel:
            self.channel = os.environ.get("VIBESENSOR_FIRMWARE_CHANNEL", "stable")
        if not self.pinned_tag:
            self.pinned_tag = os.environ.get("VIBESENSOR_FIRMWARE_PINNED_TAG", "")
        if not self.github_token:
            self.github_token = os.environ.get("GITHUB_TOKEN", "")


@dataclass
class BundleMeta:
    """Metadata about a downloaded firmware bundle (tag, asset, hash, source)."""

    tag: str = ""
    asset: str = ""
    timestamp: str = ""
    sha256: str = ""
    source: str = ""  # "downloaded" or "baseline"

    def to_dict(self) -> dict[str, str]:
        return {
            "tag": self.tag,
            "asset": self.asset,
            "timestamp": self.timestamp,
            "sha256": self.sha256,
            "source": self.source,
        }


@dataclass
class ManifestSegment:
    """A single flash segment from the ESP32 flash manifest (file, offset, hash)."""

    file: str
    offset: str
    sha256: str = ""


@dataclass
class ManifestEnvironment:
    """A flash environment (e.g. board variant) containing multiple flash segments."""

    name: str
    segments: list[ManifestSegment] = field(default_factory=list)


@dataclass
class FlashManifest:
    """Parsed contents of a ``flash.json`` firmware manifest file."""

    generated_from: str = ""
    environments: list[ManifestEnvironment] = field(default_factory=list)
