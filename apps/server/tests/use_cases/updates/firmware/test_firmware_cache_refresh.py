from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vibesensor.use_cases.updates.firmware import firmware_cache as firmware_cache_module
from vibesensor.use_cases.updates.firmware.firmware_bundle import read_meta, write_meta
from vibesensor.use_cases.updates.firmware.firmware_cache import FirmwareCache
from vibesensor.use_cases.updates.firmware.firmware_release_fetcher import (
    GitHubApiAssetRecord,
    GitHubApiReleaseRecord,
)
from vibesensor.use_cases.updates.firmware.firmware_types import BundleMeta, FirmwareCacheConfig


def _make_cache(tmp_path: Path) -> FirmwareCache:
    return FirmwareCache(
        FirmwareCacheConfig(
            cache_dir=str(tmp_path / "firmware-cache"),
            firmware_repo="Skamba/VibeSensor",
        )
    )


def _release(tag_name: str) -> GitHubApiReleaseRecord:
    return GitHubApiReleaseRecord(
        tag_name=tag_name,
        draft=False,
        prerelease=False,
        assets=[GitHubApiAssetRecord(name=f"{tag_name}.zip", url="https://example.com/fw.zip")],
    )


def _write_current_bundle(cache: FirmwareCache, *, tag: str) -> None:
    cache.current_dir.mkdir(parents=True, exist_ok=True)
    (cache.current_dir / "marker.txt").write_text(tag, encoding="utf-8")
    write_meta(
        cache.current_dir,
        BundleMeta(
            tag=tag,
            asset=f"{tag}.zip",
            timestamp="2026-01-01T00:00:00Z",
            sha256=f"sha-{tag}",
            source="downloaded",
        ),
    )


def test_refresh_download_failure_preserves_current_bundle(tmp_path: Path) -> None:
    cache = _make_cache(tmp_path)
    _write_current_bundle(cache, tag="old-tag")

    release = _release("new-tag")
    asset = release.assets[0]
    fetcher = MagicMock()
    fetcher.find_release.return_value = release
    fetcher.find_firmware_asset.return_value = asset
    fetcher.download_asset.side_effect = OSError("download failed")

    with pytest.raises(OSError, match="download failed"):
        cache.refresh(fetcher=fetcher)

    assert (cache.current_dir / "marker.txt").read_text(encoding="utf-8") == "old-tag"
    assert read_meta(cache.current_dir).tag == "old-tag"
    assert not (cache.current_dir.parent / "current.old").exists()


def test_refresh_restores_previous_bundle_after_activation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _make_cache(tmp_path)
    _write_current_bundle(cache, tag="old-tag")

    release = _release("new-tag")
    asset = release.assets[0]
    fetcher = MagicMock()
    fetcher.find_release.return_value = release
    fetcher.find_firmware_asset.return_value = asset
    fetcher.download_asset.side_effect = lambda _asset, dest: dest.write_bytes(b"bundle-bytes")

    extracted_dirs: list[Path] = []

    def fake_extract_bundle_archive(_zip_path: Path, dest: Path) -> Path:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "marker.txt").write_text("new-tag", encoding="utf-8")
        extracted_dirs.append(dest)
        return dest

    monkeypatch.setattr(
        firmware_cache_module, "extract_bundle_archive", fake_extract_bundle_archive
    )
    monkeypatch.setattr(firmware_cache_module, "validate_bundle", lambda _path: None)
    monkeypatch.setattr(firmware_cache_module, "dir_sha256", lambda _path: "sha-new")

    real_rename = Path.rename

    def fake_rename(self: Path, target: str | Path) -> Path:
        if extracted_dirs and self == extracted_dirs[0] and Path(target) == cache.current_dir:
            raise OSError("activation failed")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", fake_rename)

    with pytest.raises(OSError, match="activation failed"):
        cache.refresh(fetcher=fetcher)

    assert (cache.current_dir / "marker.txt").read_text(encoding="utf-8") == "old-tag"
    assert read_meta(cache.current_dir).tag == "old-tag"
    assert not (cache.current_dir.parent / "current.old").exists()
