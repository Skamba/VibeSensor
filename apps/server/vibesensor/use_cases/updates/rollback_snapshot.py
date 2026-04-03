"""Rollback snapshot storage for updater workflows."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from vibesensor.use_cases.updates.status import UpdateStatusRecorder

__all__ = ["RollbackSnapshot", "RollbackSnapshotMetadata", "RollbackSnapshotStore"]

_ROLLBACK_METADATA_FILE = "rollback_snapshot.json"
_ROLLBACK_WHEEL_FILE = "rollback_snapshot.whl"
_ROLLBACK_BACKUP_WHEEL_FILE = ".rollback_snapshot.previous.whl"


@dataclass(frozen=True, slots=True)
class RollbackSnapshotMetadata:
    version: str
    sha256: str


@dataclass(frozen=True, slots=True)
class RollbackSnapshot:
    metadata: RollbackSnapshotMetadata
    wheel_path: Path


@dataclass(frozen=True, slots=True)
class RollbackSnapshotPromotion:
    wheel_path: Path
    backup_path: Path | None
    moved_new_wheel: bool


class RollbackSnapshotStore:
    """Persist one canonical rollback snapshot wheel plus its metadata."""

    __slots__ = ("_rollback_dir", "_status_recorder")

    def __init__(self, rollback_dir: Path, status_recorder: UpdateStatusRecorder) -> None:
        self._rollback_dir = rollback_dir
        self._status_recorder = status_recorder

    def _metadata_path(self) -> Path:
        """Return the canonical JSON metadata path for rollback snapshot state."""

        return self._rollback_dir / _ROLLBACK_METADATA_FILE

    def snapshot_wheel_path(self) -> Path:
        """Return the canonical rollback snapshot wheel path."""

        return self._rollback_dir / _ROLLBACK_WHEEL_FILE

    def write_metadata(self, metadata: RollbackSnapshotMetadata) -> None:
        """Atomically persist rollback metadata alongside stored wheels."""

        self._rollback_dir.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps(
                {
                    "version": metadata.version,
                    "sha256": metadata.sha256,
                },
                indent=2,
            )
            + "\n"
        )
        fd, temp_path_text = tempfile.mkstemp(
            prefix=".rollback_snapshot.",
            suffix=".tmp",
            dir=self._rollback_dir,
            text=True,
        )
        temp_path = Path(temp_path_text)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
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
                self._status_recorder.add_issue(
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
                self._status_recorder.add_issue(
                    "installing",
                    "Rollback snapshot metadata is missing",
                    str(metadata_path),
                )
            return None
        try:
            raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            if report_issues:
                self._status_recorder.add_issue(
                    "installing",
                    "Rollback snapshot metadata is unreadable",
                    f"{metadata_path}: {exc}",
                )
            return None
        version = str(raw.get("version") or "")
        sha256 = str(raw.get("sha256") or "")
        if not version or not sha256:
            if report_issues:
                self._status_recorder.add_issue(
                    "installing",
                    "Rollback snapshot metadata is incomplete",
                    f"{metadata_path} is missing version or sha256",
                )
            return None
        return RollbackSnapshotMetadata(version=version, sha256=sha256)
