from __future__ import annotations

from pathlib import Path

import pytest
from test_support.firmware_bundles import write_firmware_bundle

from vibesensor.use_cases.updates.firmware.firmware_bundle import (
    flash_manifest_record_from_json,
    flash_manifest_record_to_json,
    parse_manifest,
    read_meta,
    validate_bundle,
    write_meta,
)
from vibesensor.use_cases.updates.firmware.firmware_types import (
    BundleMeta,
    FlashManifestRecord,
    ManifestEnvironmentRecord,
    ManifestSegmentRecord,
)


def test_flash_manifest_record_round_trips_and_parses_domain() -> None:
    record = FlashManifestRecord(
        generated_from="deadbeef",
        environments=[
            ManifestEnvironmentRecord(
                name="esp32dev",
                segments=[
                    ManifestSegmentRecord(
                        file="esp32dev/firmware.bin",
                        offset="0x10000",
                        sha256="a" * 64,
                    )
                ],
            )
        ],
    )

    decoded = flash_manifest_record_from_json(flash_manifest_record_to_json(record))
    manifest = parse_manifest(decoded)

    assert decoded == record
    assert manifest.generated_from == "deadbeef"
    assert manifest.environments[0].name == "esp32dev"
    assert manifest.environments[0].segments[0].file == "esp32dev/firmware.bin"


def test_write_meta_round_trips_with_read_meta(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    meta = BundleMeta(
        tag="fw-main-abc1234",
        asset="vibesensor-fw-main-abc1234.zip",
        timestamp="2026-01-01T00:00:00+00:00",
        sha256="a" * 64,
        source="downloaded",
    )

    write_meta(bundle_dir, meta)

    assert read_meta(bundle_dir) == meta


def test_read_meta_rejects_corrupt_json(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "_meta.json").write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="metadata is corrupt"):
        read_meta(bundle_dir)


def test_validate_bundle_rejects_corrupt_manifest_json(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "flash.json").write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="Firmware manifest is corrupt"):
        validate_bundle(bundle_dir)


def test_validate_bundle_succeeds(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    write_firmware_bundle(bundle_dir)

    manifest = validate_bundle(bundle_dir)

    assert len(manifest.environments) == 1
    assert manifest.environments[0].name == "m5stack_atom"


def test_validate_bundle_fails_missing_manifest(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "empty"
    bundle_dir.mkdir()

    with pytest.raises(ValueError, match="missing manifest"):
        validate_bundle(bundle_dir)


def test_validate_bundle_fails_missing_binary(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    write_firmware_bundle(bundle_dir)
    (bundle_dir / "m5stack_atom" / "firmware.bin").unlink()

    with pytest.raises(ValueError, match="missing referenced binary"):
        validate_bundle(bundle_dir)


def test_validate_bundle_fails_checksum_mismatch(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    write_firmware_bundle(bundle_dir)
    (bundle_dir / "m5stack_atom" / "firmware.bin").write_bytes(b"corrupted")

    with pytest.raises(ValueError, match="Checksum mismatch"):
        validate_bundle(bundle_dir)
