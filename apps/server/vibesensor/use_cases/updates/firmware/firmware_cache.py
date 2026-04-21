"""ESP firmware cache management: download, validate, and activate bundles from GitHub Releases.

The Pi runtime never builds firmware from source. Instead, it fetches prebuilt
firmware bundles from GitHub Releases and caches them locally. Flashing uses
only locally cached firmware (downloaded or baseline).

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

import logging
import shutil
import tempfile
from pathlib import Path

from vibesensor.use_cases.updates.firmware.firmware_bundle import (
    dir_sha256,
    extract_bundle_archive,
    read_meta,
    validate_bundle,
    write_meta,
)
from vibesensor.use_cases.updates.firmware.firmware_release_fetcher import GitHubReleaseFetcher
from vibesensor.use_cases.updates.firmware.firmware_types import (
    BundleMeta,
    FirmwareCacheConfig,
    FirmwareCacheInfoPayload,
)

LOGGER = logging.getLogger(__name__)

__all__ = ["FirmwareCache", "cache_info_cli", "refresh_cache_cli"]


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
        tag = release.tag_name
        LOGGER.info("Selected release: %s", tag)

        current_meta: BundleMeta | None = None
        if self.current_dir.is_dir():
            try:
                current_meta = read_meta(self.current_dir)
            except ValueError:
                LOGGER.warning(
                    "Current firmware cache metadata is invalid; continuing with refresh",
                    exc_info=True,
                )
        if current_meta and current_meta.tag == tag:
            LOGGER.info("Cache is already current (tag=%s). No download needed.", tag)
            return current_meta

        asset = fetcher.find_firmware_asset(release)
        asset_name = asset.name or "bundle.zip"

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(tempfile.mkdtemp(prefix="fw-staging-", dir=str(self._cache_dir)))
        target = self.current_dir
        old_current: Path | None = None
        try:
            zip_path = staging_dir / asset_name
            fetcher.download_asset(asset, zip_path)
            extract_dir = extract_bundle_archive(zip_path, staging_dir / "extracted")

            sha = dir_sha256(extract_dir)
            validate_bundle(extract_dir)

            from vibesensor.shared.time_utils import utc_now_iso

            meta = BundleMeta(
                tag=tag,
                asset=asset_name,
                timestamp=utc_now_iso(),
                sha256=sha,
                source="downloaded",
            )
            write_meta(extract_dir, meta)

            if target.exists():
                old_current = target.with_name("current.old")
                if old_current.exists():
                    shutil.rmtree(old_current)
                target.rename(old_current)
            extract_dir.rename(target)

            if old_current and old_current.exists():
                shutil.rmtree(old_current)

            LOGGER.info("Firmware cache updated: tag=%s, asset=%s", tag, asset_name)
            return meta
        except OSError:
            if old_current and old_current.exists() and not target.exists():
                try:
                    old_current.rename(target)
                    LOGGER.info("Restored previous firmware cache after activation failure")
                except OSError:
                    LOGGER.warning("Failed to restore previous firmware cache", exc_info=True)
            raise
        finally:
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
        source = "downloaded" if bundle == self.current_dir else "baseline"
        try:
            meta = read_meta(bundle)
        except ValueError as exc:
            return {
                "status": "metadata_invalid",
                "message": str(exc),
                "source": source,
                "cache_dir": str(self._cache_dir),
                "bundle_path": str(bundle),
            }
        resolved_meta = meta or BundleMeta(source=source)
        return {
            "status": "ok",
            "source": resolved_meta.source or source,
            "tag": resolved_meta.tag,
            "asset": resolved_meta.asset,
            "timestamp": resolved_meta.timestamp,
            "sha256": resolved_meta.sha256,
            "cache_dir": str(self._cache_dir),
            "bundle_path": str(bundle),
        }


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
    except (OSError, ValueError) as exc:
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
