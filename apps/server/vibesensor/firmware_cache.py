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

import hashlib
import json
import logging
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = "/var/lib/vibesensor/firmware"
_DEFAULT_FIRMWARE_REPO = "Skamba/VibeSensor"
_META_FILE = "_meta.json"
_MANIFEST_FILE = "flash.json"
_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024  # 100 MB hard limit for firmware assets


def _safe_extractall(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract *zf* into *dest*, rejecting entries that escape the target directory."""
    dest_resolved = dest.resolve()
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        if not target.is_relative_to(dest_resolved):
            raise ValueError(
                f"Zip entry '{member.filename}' would extract outside the target directory"
            )
    zf.extractall(dest)


@dataclass
class FirmwareCacheConfig:
    cache_dir: str = ""
    firmware_repo: str = _DEFAULT_FIRMWARE_REPO
    channel: str = "stable"  # "stable" or "prerelease"
    pinned_tag: str = ""
    github_token: str = ""

    def __post_init__(self) -> None:
        if not self.cache_dir:
            self.cache_dir = os.environ.get("VIBESENSOR_FIRMWARE_CACHE_DIR", _DEFAULT_CACHE_DIR)
        if not self.firmware_repo:
            self.firmware_repo = os.environ.get("VIBESENSOR_FIRMWARE_REPO", _DEFAULT_FIRMWARE_REPO)
        if not self.channel:
            self.channel = os.environ.get("VIBESENSOR_FIRMWARE_CHANNEL", "stable")
        if not self.pinned_tag:
            self.pinned_tag = os.environ.get("VIBESENSOR_FIRMWARE_PINNED_TAG", "")
        if not self.github_token:
            self.github_token = os.environ.get("GITHUB_TOKEN", "")


@dataclass
class BundleMeta:
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
    file: str
    offset: str
    sha256: str = ""


@dataclass
class ManifestEnvironment:
    name: str
    segments: list[ManifestSegment] = field(default_factory=list)


@dataclass
class FlashManifest:
    generated_from: str = ""
    environments: list[ManifestEnvironment] = field(default_factory=list)


def parse_manifest(data: dict[str, Any]) -> FlashManifest:
    """Parse a flash.json manifest dict into a FlashManifest."""
    envs: list[ManifestEnvironment] = []
    for env_data in data.get("environments", []):
        segs = [
            ManifestSegment(
                file=s["file"],
                offset=s["offset"],
                sha256=s.get("sha256", ""),
            )
            for s in env_data.get("segments", [])
        ]
        envs.append(ManifestEnvironment(name=env_data["name"], segments=segs))
    return FlashManifest(
        generated_from=data.get("generated_from", ""),
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
            "Run the updater while online or reinstall the Pi image."
        )
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Firmware manifest is corrupt in {bundle_dir}: {exc}") from exc

    manifest = parse_manifest(manifest_data)
    if not manifest.environments:
        raise ValueError(
            f"Firmware manifest in {bundle_dir} has no environments. The bundle may be incomplete."
        )

    for env in manifest.environments:
        for seg in env.segments:
            seg_path = bundle_dir / seg.file
            if not seg_path.is_file():
                raise ValueError(
                    f"Firmware bundle is missing referenced binary '{seg.file}' in {bundle_dir}. "
                    "The bundle is incomplete."
                )
            if seg.sha256:
                actual = hashlib.sha256(seg_path.read_bytes()).hexdigest()
                if actual != seg.sha256:
                    raise ValueError(
                        f"Checksum mismatch for '{seg.file}': expected {seg.sha256}, "
                        f"got {actual}. The bundle may be corrupt."
                    )
    return manifest


def read_meta(bundle_dir: Path) -> BundleMeta | None:
    """Read metadata from a bundle directory, or None if missing."""
    meta_path = bundle_dir / _META_FILE
    if not meta_path.is_file():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return BundleMeta(
        tag=data.get("tag", ""),
        asset=data.get("asset", ""),
        timestamp=data.get("timestamp", ""),
        sha256=data.get("sha256", ""),
        source=data.get("source", ""),
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
    os.replace(tmp, str(meta_path))


class GitHubReleaseFetcher:
    """Fetch firmware bundles from GitHub Releases."""

    def __init__(self, config: FirmwareCacheConfig) -> None:
        self._config = config

    def _api_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
        if self._config.github_token:
            headers["Authorization"] = f"Bearer {self._config.github_token}"
        return headers

    def _validate_url(self, url: str) -> None:
        """Ensure URL uses HTTPS to prevent insecure firmware downloads."""
        if not url.startswith("https://"):
            raise ValueError(f"Refusing non-HTTPS URL for firmware operation: {url}")

    def _api_get(self, url: str) -> Any:
        self._validate_url(url)
        req = Request(url, headers=self._api_headers())
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _download_asset(self, url: str, dest: Path) -> None:
        self._validate_url(url)
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
                        chunk = resp.read(1024 * 1024)  # 1 MB at a time
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > _MAX_DOWNLOAD_BYTES:
                            raise ValueError(
                                f"Firmware asset exceeds {_MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB "
                                f"size limit; aborting download to prevent OOM."
                            )
                        tmp_f.write(chunk)
                os.replace(tmp_path, str(dest))
            except BaseException:
                # If os.fdopen() failed, the raw fd is still open; close it.
                # Once os.fdopen() succeeds it owns the fd (closed by `with`).
                if not fdopen_ok:
                    try:
                        os.close(tmp_fd)
                    except OSError:
                        pass
                # Clean up partial temp file on any failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

    def find_release(self) -> dict[str, Any]:
        """Find the target release based on config (pinned tag, channel)."""
        owner, repo = self._config.firmware_repo.split("/", 1)
        base = f"https://api.github.com/repos/{owner}/{repo}/releases"

        if self._config.pinned_tag:
            url = f"{base}/tags/{self._config.pinned_tag}"
            LOGGER.info("Fetching pinned release: %s", self._config.pinned_tag)
            return self._api_get(url)

        LOGGER.info("Fetching releases for channel '%s'", self._config.channel)
        releases = self._api_get(f"{base}?per_page=50")
        if not isinstance(releases, list):
            raise ValueError("Unexpected GitHub API response format")

        for release in releases:
            is_prerelease = release.get("prerelease", False)
            is_draft = release.get("draft", False)
            if is_draft:
                continue
            if not self._release_has_firmware_asset(release):
                continue
            if self._config.channel == "stable" and not is_prerelease:
                return release
            if self._config.channel in ("prerelease", "edge") and is_prerelease:
                return release

        # Fallback: use the latest prerelease (firmware releases are typically prereleases)
        for release in releases:
            if release.get("draft", False):
                continue
            if not self._release_has_firmware_asset(release):
                continue
            return release

        raise ValueError(
            f"No eligible firmware release found for channel '{self._config.channel}' "
            f"in {self._config.firmware_repo}"
        )

    @staticmethod
    def _release_has_firmware_asset(release: dict[str, Any]) -> bool:
        assets = release.get("assets", [])
        for asset in assets:
            name = str(asset.get("name", ""))
            if name.startswith("vibesensor-fw-") and name.endswith(".zip"):
                return True
        return False

    def find_firmware_asset(self, release: dict[str, Any]) -> dict[str, Any]:
        """Find the firmware bundle asset in a release."""
        assets = release.get("assets", [])
        for asset in assets:
            name = asset.get("name", "")
            if name.startswith("vibesensor-fw-") and name.endswith(".zip"):
                return asset
        raise ValueError(
            f"No firmware bundle asset found in release '{release.get('tag_name', '?')}'. "
            "Expected an asset named vibesensor-fw-*.zip"
        )

    def download_bundle(self, asset: dict[str, Any], dest_dir: Path) -> Path:
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
            from .runlog import utc_now_iso

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
        except Exception:
            # Restore previous cache if we moved it aside
            if old_current and old_current.exists() and not target.exists():
                try:
                    old_current.rename(target)
                    LOGGER.info("Restored previous firmware cache after activation failure")
                except Exception:
                    LOGGER.warning("Failed to restore previous firmware cache", exc_info=True)
            # Clean up staging on failure
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
            raise
        finally:
            # Clean up staging parent if still present
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)

    def info(self) -> dict[str, Any]:
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
    for fpath in sorted(directory.rglob("*")):
        if fpath.is_file():
            h.update(str(fpath.relative_to(directory)).encode())
            h.update(b"\0")  # separator between path and content
            with open(fpath, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    h.update(chunk)
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
