from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TypedDict

import msgspec

from vibesensor.shared.constants.github import GITHUB_REPO
from vibesensor.shared.process_settings import (
    DEFAULT_FIRMWARE_CACHE_DIR,
    DEFAULT_FIRMWARE_CHANNEL,
    load_update_env_settings,
)

__all__ = [
    "BundleMeta",
    "BundleMetaRecord",
    "FirmwareCacheConfig",
    "FirmwareCacheInfoPayload",
    "FlashManifest",
    "FlashManifestRecord",
    "ManifestEnvironment",
    "ManifestEnvironmentPayload",
    "ManifestEnvironmentRecord",
    "ManifestSegment",
    "ManifestSegmentPayload",
    "ManifestSegmentRecord",
]

_DEFAULT_CACHE_DIR = str(DEFAULT_FIRMWARE_CACHE_DIR)


class ManifestSegmentPayload(TypedDict, total=False):
    file: str
    offset: str
    sha256: str


class ManifestEnvironmentPayload(TypedDict, total=False):
    name: str
    segments: list[ManifestSegmentPayload]


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


class BundleMetaRecord(msgspec.Struct, kw_only=True, frozen=True):
    tag: str = ""
    asset: str = ""
    timestamp: str = ""
    sha256: str = ""
    source: str = ""


class ManifestSegmentRecord(msgspec.Struct, kw_only=True, frozen=True):
    file: str = ""
    offset: str = ""
    sha256: str = ""


class ManifestEnvironmentRecord(msgspec.Struct, kw_only=True, frozen=True):
    name: str = ""
    segments: list[ManifestSegmentRecord] = msgspec.field(default_factory=list)


class FlashManifestRecord(msgspec.Struct, kw_only=True, frozen=True):
    generated_from: str = ""
    environments: list[ManifestEnvironmentRecord] = msgspec.field(default_factory=list)


@dataclass
class FirmwareCacheConfig:
    """Configuration for the local ESP32 firmware download cache."""

    cache_dir: str = ""
    firmware_repo: str = GITHUB_REPO
    channel: str = DEFAULT_FIRMWARE_CHANNEL  # "stable" or "prerelease"
    pinned_tag: str = ""
    github_token: str = ""

    def __post_init__(self) -> None:
        env_settings = load_update_env_settings()
        if not self.cache_dir:
            self.cache_dir = os.fspath(env_settings.firmware_cache_dir)
        if not self.firmware_repo:
            self.firmware_repo = env_settings.firmware_repo
        if not self.channel:
            self.channel = env_settings.firmware_channel
        if not self.pinned_tag:
            self.pinned_tag = env_settings.firmware_pinned_tag
        if not self.github_token:
            self.github_token = env_settings.github_token


@dataclass
class BundleMeta:
    """Metadata about a downloaded firmware bundle (tag, asset, hash, source)."""

    tag: str = ""
    asset: str = ""
    timestamp: str = ""
    sha256: str = ""
    source: str = ""  # "downloaded" or "baseline"


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
