"""Filesystem bundle helpers for firmware cache management."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path

from vibesensor.shared.types.json_types import JsonObject, is_json_array, is_json_object
from vibesensor.use_cases.updates.firmware_types import (
    BundleMeta,
    FlashManifest,
    ManifestEnvironment,
    ManifestSegment,
)

__all__ = [
    "dir_sha256",
    "extract_bundle_archive",
    "parse_manifest",
    "read_meta",
    "safe_extractall",
    "validate_bundle",
    "write_meta",
]

_META_FILE = "_meta.json"
_MANIFEST_FILE = "flash.json"


def _read_json_file(path: Path) -> JsonObject:
    """Read and parse a JSON file. Raises JSONDecodeError or OSError on failure."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not is_json_object(payload):
        raise ValueError(f"Expected JSON object in {path}, got {type(payload).__name__}")
    return payload


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


def write_meta(bundle_dir: Path, meta: BundleMeta) -> None:
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
