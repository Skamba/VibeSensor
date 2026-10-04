"""The firmware version of the bundle the flasher would use."""

from __future__ import annotations

from pathlib import Path

from test_support.firmware_bundles import write_firmware_bundle

from vibesensor.updates.firmware.esp_flash_types import SENSOR_FIRMWARE_ENV
from vibesensor.updates.firmware.firmware_cache import FirmwareCache
from vibesensor.updates.firmware.firmware_types import FirmwareCacheConfig


def _cache(tmp_path: Path) -> FirmwareCache:
    return FirmwareCache(FirmwareCacheConfig(cache_dir=str(tmp_path / "firmware")))


def test_bundled_version_follows_the_bundle_the_flasher_uses(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    assert cache.bundled_firmware_version(SENSOR_FIRMWARE_ENV) == ""

    write_firmware_bundle(cache.baseline_dir, firmware_version="2026.10.4+aaaaaaaaaaaa")
    assert cache.bundled_firmware_version(SENSOR_FIRMWARE_ENV) == "2026.10.4+aaaaaaaaaaaa"

    # A refresh activates a downloaded bundle, which takes precedence.
    write_firmware_bundle(cache.current_dir, firmware_version="2026.10.5+bbbbbbbbbbbb")
    assert cache.bundled_firmware_version(SENSOR_FIRMWARE_ENV) == "2026.10.5+bbbbbbbbbbbb"

    # A corrupt download falls back to the baseline, as flashing does.
    (cache.current_dir / SENSOR_FIRMWARE_ENV / "firmware.bin").write_bytes(b"truncated")
    assert _cache(tmp_path).bundled_firmware_version(SENSOR_FIRMWARE_ENV) == (
        "2026.10.4+aaaaaaaaaaaa"
    )


def test_bundle_from_before_version_stamping_has_no_version(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    write_firmware_bundle(cache.current_dir)

    assert cache.bundled_firmware_version(SENSOR_FIRMWARE_ENV) == ""
    assert cache.bundled_firmware_version("esp32-c3-devkitm-1") == ""
