"""Rollback snapshot storage for updater workflows."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from vibesensor.use_cases.updates.status import UpdateStatusTracker

__all__ = ["RollbackSnapshotMetadata", "RollbackSnapshotStore"]

_ROLLBACK_METADATA_FILE = "rollback_snapshot.json"


@dataclass(frozen=True, slots=True)
class RollbackSnapshotMetadata:
    version: str
    wheel_name: str
    sha256: str


class RollbackSnapshotStore:
    """Persist rollback snapshot wheel metadata and manage stored rollback wheels."""

    __slots__ = ("_rollback_dir", "_tracker")

    def __init__(self, rollback_dir: Path, tracker: UpdateStatusTracker) -> None:
        self._rollback_dir = rollback_dir
        self._tracker = tracker

    def _metadata_path(self) -> Path:
        return self._rollback_dir / _ROLLBACK_METADATA_FILE

    def write_metadata(self, metadata: RollbackSnapshotMetadata) -> None:
        self._rollback_dir.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps(
                {
                    "version": metadata.version,
                    "wheel_name": metadata.wheel_name,
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

    def rollback_wheels(self) -> list[Path]:
        return sorted(
            self._rollback_dir.glob("vibesensor-*.whl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

    def prune_wheels(self, *, keep_name: str) -> None:
        for old_wheel in self.rollback_wheels():
            if old_wheel.name != keep_name:
                old_wheel.unlink(missing_ok=True)

    def load_metadata(self) -> RollbackSnapshotMetadata | None:
        metadata_path = self._metadata_path()
        if not metadata_path.is_file():
            return None
        try:
            raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            self._tracker.add_issue(
                "installing",
                "Rollback metadata is unreadable",
                f"{metadata_path}: {exc}",
            )
            return None
        version = str(raw.get("version") or "")
        wheel_name = str(raw.get("wheel_name") or "")
        sha256 = str(raw.get("sha256") or "")
        if not version or not wheel_name or not sha256:
            self._tracker.add_issue(
                "installing",
                "Rollback metadata is incomplete",
                f"{metadata_path} is missing version, wheel_name, or sha256",
            )
            return None
        return RollbackSnapshotMetadata(version=version, wheel_name=wheel_name, sha256=sha256)
