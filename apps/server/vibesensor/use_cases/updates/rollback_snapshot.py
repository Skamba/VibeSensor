"""Rollback snapshot storage for updater workflows."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import msgspec

from vibesensor.use_cases.updates.status import UpdateStatusTracker

__all__ = ["RollbackSnapshot", "RollbackSnapshotMetadata", "RollbackSnapshotStore"]

_ROLLBACK_METADATA_FILE = "rollback_snapshot.json"
_ROLLBACK_WHEEL_FILE = "rollback_snapshot.whl"
_ROLLBACK_BACKUP_WHEEL_FILE = ".rollback_snapshot.previous.whl"


class _RollbackSnapshotMetadataRecord(msgspec.Struct, kw_only=True, frozen=True):
    version: str = ""
    sha256: str = ""
    config_path: str = ""
    repo_path: str = ""
    static_assets_hash: str = ""
    static_build_source_hash: str = ""
    static_build_commit: str = ""
    assets_verified: bool = False
    has_packaged_static: bool = False


@dataclass(frozen=True, slots=True)
class RollbackSnapshotMetadata:
    version: str
    sha256: str
    config_path: str = ""
    repo_path: str = ""
    static_assets_hash: str = ""
    static_build_source_hash: str = ""
    static_build_commit: str = ""
    assets_verified: bool = False
    has_packaged_static: bool = False


@dataclass(frozen=True, slots=True)
class RollbackSnapshot:
    metadata: RollbackSnapshotMetadata
    wheel_path: Path


@dataclass(frozen=True, slots=True)
class RollbackSnapshotPromotion:
    wheel_path: Path
    backup_path: Path | None
    moved_new_wheel: bool


def _rollback_snapshot_metadata_to_json(metadata: RollbackSnapshotMetadata) -> bytes:
    return (
        msgspec.json.encode(
            _RollbackSnapshotMetadataRecord(
                version=metadata.version,
                sha256=metadata.sha256,
                config_path=metadata.config_path,
                repo_path=metadata.repo_path,
                static_assets_hash=metadata.static_assets_hash,
                static_build_source_hash=metadata.static_build_source_hash,
                static_build_commit=metadata.static_build_commit,
                assets_verified=metadata.assets_verified,
                has_packaged_static=metadata.has_packaged_static,
            )
        )
        + b"\n"
    )


def _rollback_snapshot_metadata_from_json(raw: bytes | str) -> RollbackSnapshotMetadata:
    record = _decode_rollback_snapshot_metadata_record(raw)
    return _rollback_snapshot_metadata_from_record(record)


def _decode_rollback_snapshot_metadata_record(raw: bytes | str) -> _RollbackSnapshotMetadataRecord:
    try:
        return msgspec.json.decode(raw, type=_RollbackSnapshotMetadataRecord)
    except msgspec.ValidationError:
        decoded = msgspec.json.decode(raw)
        if not isinstance(decoded, Mapping):
            raise
        return _rollback_snapshot_metadata_record_from_object(decoded)


def _rollback_snapshot_metadata_record_from_object(
    payload: Mapping[str, object],
) -> _RollbackSnapshotMetadataRecord:
    return _RollbackSnapshotMetadataRecord(
        version=_rollback_snapshot_metadata_text(payload.get("version")),
        sha256=_rollback_snapshot_metadata_text(payload.get("sha256")),
        config_path=_rollback_snapshot_metadata_text(payload.get("config_path")),
        repo_path=_rollback_snapshot_metadata_text(payload.get("repo_path")),
        static_assets_hash=_rollback_snapshot_metadata_text(payload.get("static_assets_hash")),
        static_build_source_hash=_rollback_snapshot_metadata_text(
            payload.get("static_build_source_hash")
        ),
        static_build_commit=_rollback_snapshot_metadata_text(payload.get("static_build_commit")),
        assets_verified=bool(payload.get("assets_verified")),
        has_packaged_static=bool(payload.get("has_packaged_static")),
    )


def _rollback_snapshot_metadata_text(value: object) -> str:
    return str(value or "")


def _rollback_snapshot_metadata_from_record(
    record: _RollbackSnapshotMetadataRecord,
) -> RollbackSnapshotMetadata:
    return RollbackSnapshotMetadata(
        version=record.version,
        sha256=record.sha256,
        config_path=record.config_path,
        repo_path=record.repo_path,
        static_assets_hash=record.static_assets_hash,
        static_build_source_hash=record.static_build_source_hash,
        static_build_commit=record.static_build_commit,
        assets_verified=record.assets_verified,
        has_packaged_static=record.has_packaged_static,
    )


class RollbackSnapshotStore:
    """Persist one canonical rollback snapshot wheel plus its metadata."""

    __slots__ = ("_rollback_dir", "_status")

    def __init__(self, rollback_dir: Path, status: UpdateStatusTracker) -> None:
        self._rollback_dir = rollback_dir
        self._status = status

    def _metadata_path(self) -> Path:
        """Return the canonical JSON metadata path for rollback snapshot state."""

        return self._rollback_dir / _ROLLBACK_METADATA_FILE

    def snapshot_wheel_path(self) -> Path:
        """Return the canonical rollback snapshot wheel path."""

        return self._rollback_dir / _ROLLBACK_WHEEL_FILE

    def write_metadata(self, metadata: RollbackSnapshotMetadata) -> None:
        """Atomically persist rollback metadata alongside stored wheels."""

        self._rollback_dir.mkdir(parents=True, exist_ok=True)
        payload = _rollback_snapshot_metadata_to_json(metadata)
        fd, temp_path_text = tempfile.mkstemp(
            prefix=".rollback_snapshot.",
            suffix=".tmp",
            dir=self._rollback_dir,
        )
        temp_path = Path(temp_path_text)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self._metadata_path())
        finally:
            temp_path.unlink(missing_ok=True)

    def replace_snapshot_wheel(self, wheel_path: Path) -> RollbackSnapshotPromotion:
        """Promote *wheel_path* into the canonical rollback snapshot location."""

        self._rollback_dir.mkdir(parents=True, exist_ok=True)
        snapshot_wheel_path = self.snapshot_wheel_path()
        moved_new_wheel = wheel_path != snapshot_wheel_path
        backup_path: Path | None = None
        if moved_new_wheel:
            if snapshot_wheel_path.is_file():
                backup_path = self._rollback_dir / _ROLLBACK_BACKUP_WHEEL_FILE
                backup_path.unlink(missing_ok=True)
                snapshot_wheel_path.replace(backup_path)
            wheel_path.replace(snapshot_wheel_path)
        return RollbackSnapshotPromotion(
            wheel_path=snapshot_wheel_path,
            backup_path=backup_path,
            moved_new_wheel=moved_new_wheel,
        )

    def commit_snapshot_wheel(self, promotion: RollbackSnapshotPromotion) -> None:
        """Finalize a promoted rollback wheel after metadata succeeds."""

        if promotion.backup_path is not None:
            promotion.backup_path.unlink(missing_ok=True)

    def rollback_snapshot_wheel(self, promotion: RollbackSnapshotPromotion) -> None:
        """Undo a promoted rollback wheel after metadata persistence fails."""

        if promotion.backup_path is not None:
            promotion.wheel_path.unlink(missing_ok=True)
            promotion.backup_path.replace(self.snapshot_wheel_path())
            return
        if promotion.moved_new_wheel:
            promotion.wheel_path.unlink(missing_ok=True)

    def remove_snapshot(self) -> None:
        """Delete the current rollback snapshot wheel and metadata when invalidated."""

        self.snapshot_wheel_path().unlink(missing_ok=True)
        self._metadata_path().unlink(missing_ok=True)
        (self._rollback_dir / _ROLLBACK_BACKUP_WHEEL_FILE).unlink(missing_ok=True)

    def load_snapshot(self, *, report_issues: bool = True) -> RollbackSnapshot | None:
        """Load the canonical rollback snapshot, optionally reporting problems."""

        metadata = self._load_metadata(report_issues=report_issues)
        if metadata is None:
            return None
        wheel_path = self.snapshot_wheel_path()
        if not wheel_path.is_file():
            if report_issues:
                self._status.add_issue(
                    "installing",
                    "Rollback snapshot wheel is missing",
                    str(wheel_path),
                )
            return None
        return RollbackSnapshot(metadata=metadata, wheel_path=wheel_path)

    def _load_metadata(self, *, report_issues: bool) -> RollbackSnapshotMetadata | None:
        metadata_path = self._metadata_path()
        if not metadata_path.is_file():
            if report_issues:
                self._status.add_issue(
                    "installing",
                    "Rollback snapshot metadata is missing",
                    str(metadata_path),
                )
            return None
        try:
            metadata = _rollback_snapshot_metadata_from_json(metadata_path.read_bytes())
        except (msgspec.DecodeError, msgspec.ValidationError, OSError) as exc:
            if report_issues:
                self._status.add_issue(
                    "installing",
                    "Rollback snapshot metadata is unreadable",
                    f"{metadata_path}: {exc}",
                )
            return None
        if not metadata.version or not metadata.sha256:
            if report_issues:
                self._status.add_issue(
                    "installing",
                    "Rollback snapshot metadata is incomplete",
                    f"{metadata_path} is missing version or sha256",
                )
            return None
        return metadata
