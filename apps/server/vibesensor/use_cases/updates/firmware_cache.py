"""ESP firmware cache management: download, validate, and activate bundles from GitHub Releases.

The Pi runtime never builds firmware from source. Instead, it fetches prebuilt
firmware bundles from GitHub Releases and caches them locally. Flashing uses
only locally cached firmware (downloaded or baseline).

Bundle layout (inside a zip or extracted directory)::

    flash.json              # manifest with environments[].segments[]{file, offset, sha256}
    m5stack_atom/
        bootloader.bin
        partitions.bin
        firmware.bin
        boot_app0.bin       # optional

Cache directory structure::

    <cache_root>/
        current/            # atomically activated downloaded bundle
            flash.json
            m5stack_atom/...
            _meta.json      # {tag, asset, timestamp, sha256, source: "downloaded"}
        baseline/           # embedded in Pi image at build time
            flash.json
            m5stack_atom/...
            _meta.json      # {tag, asset, timestamp, sha256, source: "baseline"}
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict
from urllib.request import Request, urlopen

from vibesensor.shared.constants import GITHUB_REPO
from vibesensor.shared.types.json_types import JsonObject, is_json_array, is_json_object
from vibesensor.use_cases.updates.release_fetcher import (
    DOWNLOAD_CHUNK_BYTES,
    GitHubAPIClient,
    validate_https_url,
)

LOGGER = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = "/var/lib/vibesensor/firmware"
_META_FILE = "_meta.json"
_MANIFEST_FILE = "flash.json"
_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024  # 100 MB hard limit for firmware assets

_FW_ASSET_PREFIX = "vibesensor-fw-"
_FW_ASSET_SUFFIX = ".zip"


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


def _coerce_release_asset_payload(raw: JsonObject) -> GitHubReleaseAssetPayload:
    payload: GitHubReleaseAssetPayload = {}
    name = raw.get("name")
    url = raw.get("url")
    if isinstance(name, str):
        payload["name"] = name
    if isinstance(url, str):
        payload["url"] = url
    return payload


def _coerce_release_payload(raw: JsonObject) -> GitHubReleasePayload:
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


def _is_firmware_asset_name(name: str) -> bool:
    """Return True if *name* matches the firmware bundle naming convention."""
    return name.startswith(_FW_ASSET_PREFIX) and name.endswith(_FW_ASSET_SUFFIX)


def _read_json_file(path: Path) -> JsonObject:
    """Read and parse a JSON file. Raises JSONDecodeError or OSError on failure."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not is_json_object(payload):
        raise ValueError(f"Expected JSON object in {path}, got {type(payload).__name__}")
    return payload


def _safe_extractall(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract *zf* into *dest*, rejecting entries that escape the target directory."""
    dest_resolved = dest.resolve()
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        if not target.is_relative_to(dest_resolved):
            raise ValueError(
                f"Zip entry '{member.filename}' would extract outside the target directory",
            )
    zf.extractall(dest)


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


def parse_manifest(data: JsonObject) -> FlashManifest:
    """Parse a flash.json manifest dict into a FlashManifest."""
    envs: list[ManifestEnvironment] = []
    environments = data.get("environments", [])
    if is_json_array(environments):
        for env_data in environments:
            if not is_json_object(env_data):
                continue
            segments_raw = env_data.get("segments", [])
            segs: list[ManifestSegment] = []
            if is_json_array(segments_raw):
                for segment in segments_raw:
                    if not is_json_object(segment):
                        continue
                    file_name = segment.get("file")
                    offset = segment.get("offset")
                    if not isinstance(file_name, str) or not isinstance(offset, str):
                        continue
                    sha256 = segment.get("sha256", "")
                    segs.append(
                        ManifestSegment(
                            file=file_name,
                            offset=offset,
                            sha256=str(sha256) if isinstance(sha256, str) else "",
                        ),
                    )
            name = env_data.get("name")
            if isinstance(name, str) and name:
                envs.append(ManifestEnvironment(name=name, segments=segs))
    return FlashManifest(
        generated_from=str(data.get("generated_from", "")),
        environments=envs,
    )


def validate_bundle(bundle_dir: Path) -> FlashManifest:
    """Validate a firmware bundle directory.

    Raises ValueError with an actionable message if validation fails.
    Returns the parsed manifest on success.
    """
    manifest_path = bundle_dir / _MANIFEST_FILE
    if not manifest_path.is_file():
        raise ValueError(
            f"Firmware bundle is missing manifest ({_MANIFEST_FILE}) in {bundle_dir}. "
            "Run the updater while online or reinstall the Pi image.",
        )
    try:
        manifest_data = _read_json_file(manifest_path)
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Firmware manifest is corrupt in {bundle_dir}: {exc}") from exc

    manifest = parse_manifest(manifest_data)
    if not manifest.environments:
        raise ValueError(
            f"Firmware manifest in {bundle_dir} has no environments. The bundle may be incomplete.",
        )

    for env in manifest.environments:
        for seg in env.segments:
            seg_path = bundle_dir / seg.file
            if not seg_path.is_file():
                raise ValueError(
                    f"Firmware bundle is missing referenced binary '{seg.file}' in {bundle_dir}. "
                    "The bundle is incomplete.",
                )
            if seg.sha256:
                actual = hashlib.sha256(seg_path.read_bytes()).hexdigest()
                if actual != seg.sha256:
                    raise ValueError(
                        f"Checksum mismatch for '{seg.file}': expected {seg.sha256}, "
                        f"got {actual}. The bundle may be corrupt.",
                    )
    return manifest


def read_meta(bundle_dir: Path) -> BundleMeta | None:
    """Read metadata from a bundle directory, or None if missing."""
    meta_path = bundle_dir / _META_FILE
    if not meta_path.is_file():
        return None
    try:
        data = _read_json_file(meta_path)
    except (json.JSONDecodeError, OSError):
        return None
    return BundleMeta(
        tag=str(data.get("tag", "")),
        asset=str(data.get("asset", "")),
        timestamp=str(data.get("timestamp", "")),
        sha256=str(data.get("sha256", "")),
        source=str(data.get("source", "")),
    )


def _write_meta(bundle_dir: Path, meta: BundleMeta) -> None:
    """Atomically write metadata to the bundle directory.

    Uses a temp-file + ``os.replace`` so a crash mid-write never leaves
    a truncated ``_meta.json``.
    """
    meta_path = bundle_dir / _META_FILE
    payload = json.dumps(meta.to_dict(), indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(
        dir=str(bundle_dir),
        prefix="._meta_",
        suffix=".tmp",
    )
    try:
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    Path(tmp).replace(meta_path)


class GitHubReleaseFetcher(GitHubAPIClient):
    """Fetch firmware bundles from GitHub Releases."""

    def __init__(self, config: FirmwareCacheConfig) -> None:
        self._config = config
        self._github_token = config.github_token
        self._api_context = "firmware"

    def _download_asset(self, url: str, dest: Path) -> None:
        validate_https_url(url, context="firmware")
        headers = self._api_headers()
        headers["Accept"] = "application/octet-stream"
        req = Request(url, headers=headers)
        with urlopen(req, timeout=120) as resp:
            # Stream directly to a temp file to avoid buffering the entire
            # firmware binary in memory (Pi 3A+ has only 512 MB RAM).
            tmp_fd, tmp_path = tempfile.mkstemp(dir=str(dest.parent), suffix=".dl_tmp")
            fdopen_ok = False
            try:
                total = 0
                with os.fdopen(tmp_fd, "wb") as tmp_f:
                    fdopen_ok = True
                    while True:
                        chunk = resp.read(DOWNLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > _MAX_DOWNLOAD_BYTES:
                            raise ValueError(
                                f"Firmware asset exceeds {_MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB "
                                f"size limit; aborting download to prevent OOM.",
                            )
                        tmp_f.write(chunk)
                Path(tmp_path).replace(dest)
            except BaseException:
                # If os.fdopen() failed, the raw fd is still open; close it.
                # Once os.fdopen() succeeds it owns the fd (closed by `with`).
                if not fdopen_ok:
                    with contextlib.suppress(OSError):
                        os.close(tmp_fd)
                # Clean up partial temp file on any failure
                with contextlib.suppress(OSError):
                    Path(tmp_path).unlink()
                raise

    def find_release(self) -> GitHubReleasePayload:
        """Find the target release based on config (pinned tag, channel)."""
        owner, repo = self._config.firmware_repo.split("/", 1)
        base = f"https://api.github.com/repos/{owner}/{repo}/releases"

        if self._config.pinned_tag:
            url = f"{base}/tags/{self._config.pinned_tag}"
            LOGGER.info("Fetching pinned release: %s", self._config.pinned_tag)
            release = self._api_get(url)
            if not is_json_object(release):
                raise ValueError("Unexpected GitHub API response format")
            return _coerce_release_payload(release)

        LOGGER.info("Fetching releases for channel '%s'", self._config.channel)
        releases = self._api_get(f"{base}?per_page=50")
        if not isinstance(releases, list):
            raise ValueError("Unexpected GitHub API response format")

        for release in releases:
            if not is_json_object(release):
                continue
            is_prerelease = release.get("prerelease", False)
            is_draft = release.get("draft", False)
            if is_draft:
                continue
            release_payload = _coerce_release_payload(release)
            if not self._release_has_firmware_asset(release_payload):
                continue
            if self._config.channel == "stable" and not is_prerelease:
                return release_payload
            if self._config.channel in ("prerelease", "edge") and is_prerelease:
                return release_payload

        # Fallback: use the latest prerelease (firmware releases are typically prereleases)
        for release in releases:
            if not is_json_object(release):
                continue
            if release.get("draft", False):
                continue
            release_payload = _coerce_release_payload(release)
            if not self._release_has_firmware_asset(release_payload):
                continue
            return release_payload

        raise ValueError(
            f"No eligible firmware release found for channel '{self._config.channel}' "
            f"in {self._config.firmware_repo}",
        )

    @staticmethod
    def _release_has_firmware_asset(release: GitHubReleasePayload) -> bool:
        return any(
            _is_firmware_asset_name(str(a.get("name", ""))) for a in release.get("assets", [])
        )

    def find_firmware_asset(self, release: GitHubReleasePayload) -> GitHubReleaseAssetPayload:
        """Find the firmware bundle asset in a release."""
        for asset in release.get("assets", []):
            if _is_firmware_asset_name(str(asset.get("name", ""))):
                return asset
        raise ValueError(
            f"No firmware bundle asset found in release '{release.get('tag_name', '?')}'. "
            "Expected an asset named vibesensor-fw-*.zip",
        )

    def download_bundle(self, asset: GitHubReleaseAssetPayload, dest_dir: Path) -> Path:
        """Download and extract a firmware bundle asset."""
        asset_url = asset.get("url", "")
        asset_name = asset.get("name", "bundle.zip")
        zip_path = dest_dir / asset_name
        LOGGER.info("Downloading firmware asset: %s", asset_name)
        self._download_asset(asset_url, zip_path)
        extract_dir = dest_dir / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extractall(zf, extract_dir)
        zip_path.unlink()
        return extract_dir


class FirmwareCache:
    """Manage local firmware cache with downloaded and baseline bundles."""

    def __init__(self, config: FirmwareCacheConfig | None = None) -> None:
        self._config = config or FirmwareCacheConfig()
        self._cache_dir = Path(self._config.cache_dir)

    @property
    def current_dir(self) -> Path:
        return self._cache_dir / "current"

    @property
    def baseline_dir(self) -> Path:
        return self._cache_dir / "baseline"

    def active_bundle_dir(self) -> Path | None:
        """Return the active firmware bundle directory, or None.

        Selection rules:
        1. If a validated downloaded cache exists, use it.
        2. Else if an embedded baseline exists and validates, use it.
        3. Else None.
        """
        if self.current_dir.is_dir():
            try:
                validate_bundle(self.current_dir)
                return self.current_dir
            except ValueError:
                LOGGER.warning("Downloaded cache is invalid; checking baseline")
        if self.baseline_dir.is_dir():
            try:
                validate_bundle(self.baseline_dir)
                return self.baseline_dir
            except ValueError:
                LOGGER.warning("Baseline bundle is also invalid")
        return None

    def active_meta(self) -> BundleMeta | None:
        """Return metadata for the active bundle."""
        bundle = self.active_bundle_dir()
        if bundle is None:
            return None
        return read_meta(bundle)

    def refresh(self, fetcher: GitHubReleaseFetcher | None = None) -> BundleMeta:
        """Download and activate the latest firmware bundle.

        Returns the metadata of the activated bundle.
        Raises on failure, leaving the existing cache unchanged.
        """
        if fetcher is None:
            fetcher = GitHubReleaseFetcher(self._config)

        release = fetcher.find_release()
        tag = release.get("tag_name", "")
        LOGGER.info("Selected release: %s", tag)

        # Check if already current
        current_meta = read_meta(self.current_dir) if self.current_dir.is_dir() else None
        if current_meta and current_meta.tag == tag:
            LOGGER.info("Cache is already current (tag=%s). No download needed.", tag)
            return current_meta

        asset = fetcher.find_firmware_asset(release)
        asset_name = asset.get("name", "")

        # Download to a temporary directory
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(tempfile.mkdtemp(prefix="fw-staging-", dir=str(self._cache_dir)))
        target = self.current_dir
        old_current: Path | None = None
        try:
            extract_dir = fetcher.download_bundle(asset, staging_dir)

            # Compute SHA256 of the downloaded content
            sha = _dir_sha256(extract_dir)

            # Validate the bundle
            validate_bundle(extract_dir)

            # Write metadata
            from vibesensor.adapters.persistence.runlog import utc_now_iso

            meta = BundleMeta(
                tag=tag,
                asset=asset_name,
                timestamp=utc_now_iso(),
                sha256=sha,
                source="downloaded",
            )
            _write_meta(extract_dir, meta)

            # Atomic activation: rename staging → current
            # NOTE: target/old_current initialised before try (line above)
            # so the except handler can always reference them safely.
            if target.exists():
                old_current = target.with_name("current.old")
                if old_current.exists():
                    shutil.rmtree(old_current)
                target.rename(old_current)
            extract_dir.rename(target)

            # Clean up old
            if old_current and old_current.exists():
                shutil.rmtree(old_current)

            LOGGER.info("Firmware cache updated: tag=%s, asset=%s", tag, asset_name)
            return meta
        except OSError:
            # Restore previous cache if we moved it aside
            if old_current and old_current.exists() and not target.exists():
                try:
                    old_current.rename(target)
                    LOGGER.info("Restored previous firmware cache after activation failure")
                except OSError:
                    LOGGER.warning("Failed to restore previous firmware cache", exc_info=True)
            # Staging cleanup is handled by the finally block below.
            raise
        finally:
            # Clean up staging parent if still present
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)

    def info(self) -> FirmwareCacheInfoPayload:
        """Return info about the active firmware cache."""
        bundle = self.active_bundle_dir()
        if bundle is None:
            return {
                "status": "no_firmware",
                "message": (
                    "No valid firmware bundle found. "
                    "Run the updater while online or reinstall Pi image."
                ),
            }
        meta = read_meta(bundle) or BundleMeta()
        return {
            "status": "ok",
            "source": meta.source or ("downloaded" if bundle == self.current_dir else "baseline"),
            "tag": meta.tag,
            "asset": meta.asset,
            "timestamp": meta.timestamp,
            "sha256": meta.sha256,
            "cache_dir": str(self._cache_dir),
            "bundle_path": str(bundle),
        }


def _dir_sha256(directory: Path) -> str:
    """Compute a SHA256 hash over all files in a directory (sorted, deterministic)."""
    h = hashlib.sha256()
    _update = h.update  # local-bind for the tight read loop
    for fpath in sorted(directory.rglob("*")):
        if fpath.is_file():
            _update(str(fpath.relative_to(directory)).encode())
            _update(b"\0")  # separator between path and content
            with fpath.open("rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    _update(chunk)
    return h.hexdigest()


def refresh_cache_cli() -> None:
    """CLI entry point: refresh the firmware cache."""
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Refresh ESP firmware cache from GitHub Releases")
    parser.add_argument("--cache-dir", default="", help="Cache directory")
    parser.add_argument("--repo", default="", help="GitHub owner/repo")
    parser.add_argument("--channel", default="", help="Release channel (stable/prerelease)")
    parser.add_argument("--tag", default="", help="Pin to a specific release tag")
    args = parser.parse_args()

    config = FirmwareCacheConfig(
        cache_dir=args.cache_dir,
        firmware_repo=args.repo,
        channel=args.channel,
        pinned_tag=args.tag,
    )
    cache = FirmwareCache(config)
    try:
        meta = cache.refresh()
        print(f"Firmware cache refreshed: tag={meta.tag}, asset={meta.asset}")
        print(f"Source: {meta.source}, SHA256: {meta.sha256}")
    except Exception as exc:
        print(f"ERROR: Firmware cache refresh failed: {exc}", file=sys.stderr)
        print(
            "Flashing will not work until an online update succeeds.",
            file=sys.stderr,
        )
        sys.exit(1)


def cache_info_cli() -> None:
    """CLI entry point: print active firmware cache info."""
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Show active ESP firmware cache info")
    parser.add_argument("--cache-dir", default="", help="Cache directory")
    args = parser.parse_args()

    config = FirmwareCacheConfig(cache_dir=args.cache_dir)
    cache = FirmwareCache(config)
    info = cache.info()
    for key, val in info.items():
        print(f"{key}: {val}")


if __name__ == "__main__":
    refresh_cache_cli()
