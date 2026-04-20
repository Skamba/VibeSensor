"""Filesystem bundle helpers for firmware cache management."""

from __future__ import annotations

import hashlib
import os
import tempfile
import zipfile
from collections.abc import Mapping
from pathlib import Path

import msgspec

from vibesensor.shared.types.json_types import is_json_array, is_json_object
from vibesensor.use_cases.updates.firmware.firmware_types import (
    BundleMeta,
    BundleMetaRecord,
    FlashManifest,
    FlashManifestRecord,
    ManifestEnvironment,
    ManifestEnvironmentRecord,
    ManifestSegment,
    ManifestSegmentRecord,
)

__all__ = [
    "bundle_meta_record_from_json",
    "bundle_meta_record_to_json",
    "dir_sha256",
    "extract_bundle_archive",
    "flash_manifest_record_from_json",
    "flash_manifest_record_to_json",
    "parse_manifest",
    "read_meta",
    "safe_extractall",
    "validate_bundle",
    "write_meta",
]

_META_FILE = "_meta.json"
_MANIFEST_FILE = "flash.json"


def flash_manifest_record_from_json(raw: bytes | str) -> FlashManifestRecord:
    try:
        return msgspec.json.decode(raw, type=FlashManifestRecord)
    except msgspec.ValidationError as exc:
        decoded = msgspec.json.decode(raw)
        if not is_json_object(decoded):
            raise ValueError("Firmware manifest root must be a JSON object") from exc
        return _flash_manifest_record_from_object(decoded)


def flash_manifest_record_to_json(record: FlashManifestRecord) -> bytes:
    return msgspec.json.encode(record) + b"\n"


def bundle_meta_record_from_json(raw: bytes | str) -> BundleMetaRecord:
    try:
        return msgspec.json.decode(raw, type=BundleMetaRecord)
    except msgspec.ValidationError as exc:
        decoded = msgspec.json.decode(raw)
        if not is_json_object(decoded):
            raise ValueError("Firmware bundle metadata root must be a JSON object") from exc
        return _bundle_meta_record_from_object(decoded)


def bundle_meta_record_to_json(record: BundleMetaRecord) -> bytes:
    return msgspec.json.encode(record) + b"\n"


def safe_extractall(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract *zf* into *dest*, rejecting entries that escape the target directory."""
    dest_resolved = dest.resolve()
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        if not target.is_relative_to(dest_resolved):
            raise ValueError(
                f"Zip entry '{member.filename}' would extract outside the target directory",
            )
    zf.extractall(dest)


def extract_bundle_archive(zip_path: Path, dest_dir: Path) -> Path:
    """Extract a downloaded firmware bundle archive into *dest_dir*."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        safe_extractall(zf, dest_dir)
    zip_path.unlink()
    return dest_dir


def parse_manifest(data: FlashManifestRecord | object) -> FlashManifest:
    """Parse a flash.json manifest record or JSON-like object into a FlashManifest."""

    record = _coerce_flash_manifest_record(data)
    envs: list[ManifestEnvironment] = []
    for env_record in record.environments:
        if not env_record.name:
            continue
        envs.append(
            ManifestEnvironment(
                name=env_record.name,
                segments=[
                    ManifestSegment(
                        file=segment.file,
                        offset=segment.offset,
                        sha256=segment.sha256,
                    )
                    for segment in env_record.segments
                    if segment.file and segment.offset
                ],
            )
        )
    return FlashManifest(
        generated_from=record.generated_from,
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
        manifest_record = flash_manifest_record_from_json(manifest_path.read_bytes())
    except (msgspec.DecodeError, OSError, ValueError) as exc:
        raise ValueError(f"Firmware manifest is corrupt in {bundle_dir}: {exc}") from exc

    manifest = parse_manifest(manifest_record)
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
        record = bundle_meta_record_from_json(meta_path.read_bytes())
    except (msgspec.DecodeError, OSError, ValueError) as exc:
        raise ValueError(f"Firmware bundle metadata is corrupt in {bundle_dir}: {exc}") from exc
    return BundleMeta(
        tag=record.tag,
        asset=record.asset,
        timestamp=record.timestamp,
        sha256=record.sha256,
        source=record.source,
    )


def write_meta(bundle_dir: Path, meta: BundleMeta) -> None:
    """Atomically write metadata to the bundle directory.

    Uses a temp-file + ``os.replace`` so a crash mid-write never leaves
    a truncated ``_meta.json``.
    """
    meta_path = bundle_dir / _META_FILE
    payload = bundle_meta_record_to_json(
        BundleMetaRecord(
            tag=meta.tag,
            asset=meta.asset,
            timestamp=meta.timestamp,
            sha256=meta.sha256,
            source=meta.source,
        )
    )
    fd, tmp = tempfile.mkstemp(
        dir=str(bundle_dir),
        prefix="._meta_",
        suffix=".tmp",
    )
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    Path(tmp).replace(meta_path)


def _coerce_flash_manifest_record(data: FlashManifestRecord | object) -> FlashManifestRecord:
    if isinstance(data, FlashManifestRecord):
        return data
    if not is_json_object(data):
        return FlashManifestRecord()
    return _flash_manifest_record_from_object(data)


def _flash_manifest_record_from_object(payload: Mapping[str, object]) -> FlashManifestRecord:
    environments: list[ManifestEnvironmentRecord] = []
    raw_environments = payload.get("environments")
    if is_json_array(raw_environments):
        for raw_environment in raw_environments:
            if is_json_object(raw_environment):
                environments.append(_manifest_environment_record_from_object(raw_environment))
            else:
                environments.append(ManifestEnvironmentRecord())
    return FlashManifestRecord(
        generated_from=str(payload.get("generated_from", "")),
        environments=environments,
    )


def _manifest_environment_record_from_object(
    payload: Mapping[str, object],
) -> ManifestEnvironmentRecord:
    segments: list[ManifestSegmentRecord] = []
    raw_segments = payload.get("segments")
    if is_json_array(raw_segments):
        for raw_segment in raw_segments:
            if is_json_object(raw_segment):
                segments.append(_manifest_segment_record_from_object(raw_segment))
            else:
                segments.append(ManifestSegmentRecord())
    name = payload.get("name")
    return ManifestEnvironmentRecord(
        name=name if isinstance(name, str) else "",
        segments=segments,
    )


def _manifest_segment_record_from_object(payload: Mapping[str, object]) -> ManifestSegmentRecord:
    file_name = payload.get("file")
    offset = payload.get("offset")
    sha256 = payload.get("sha256", "")
    return ManifestSegmentRecord(
        file=file_name if isinstance(file_name, str) else "",
        offset=offset if isinstance(offset, str) else "",
        sha256=sha256 if isinstance(sha256, str) else "",
    )


def _bundle_meta_record_from_object(payload: Mapping[str, object]) -> BundleMetaRecord:
    return BundleMetaRecord(
        tag=str(payload.get("tag", "")),
        asset=str(payload.get("asset", "")),
        timestamp=str(payload.get("timestamp", "")),
        sha256=str(payload.get("sha256", "")),
        source=str(payload.get("source", "")),
    )


def dir_sha256(directory: Path) -> str:
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
