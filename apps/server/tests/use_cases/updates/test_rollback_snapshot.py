from __future__ import annotations

from pathlib import Path

from test_support.update_status import build_update_status_harness

from vibesensor.use_cases.updates.rollback_snapshot import (
    RollbackSnapshotMetadata,
    RollbackSnapshotStore,
)
from vibesensor.use_cases.updates.status import UpdateStatusTracker


def _make_store(tmp_path: Path) -> tuple[RollbackSnapshotStore, UpdateStatusTracker, Path]:
    rollback_dir = tmp_path / "rollback"
    tracker = build_update_status_harness(tmp_path / "update_status.json")
    return RollbackSnapshotStore(rollback_dir, tracker), tracker, rollback_dir


def test_rollback_snapshot_metadata_round_trips(tmp_path: Path) -> None:
    store, tracker, _rollback_dir = _make_store(tmp_path)
    metadata = RollbackSnapshotMetadata(version="2025.6.14", sha256="a" * 64)

    store.write_metadata(metadata)

    assert store._load_metadata(report_issues=True) == metadata
    assert tracker.status.issues == []


def test_rollback_snapshot_metadata_reports_unreadable_json(tmp_path: Path) -> None:
    store, tracker, rollback_dir = _make_store(tmp_path)
    rollback_dir.mkdir()
    (rollback_dir / "rollback_snapshot.json").write_text("{not-json\n", encoding="utf-8")

    assert store._load_metadata(report_issues=True) is None
    assert any(
        issue.message == "Rollback snapshot metadata is unreadable"
        for issue in tracker.status.issues
    )


def test_rollback_snapshot_metadata_reports_incomplete_payload(tmp_path: Path) -> None:
    store, tracker, rollback_dir = _make_store(tmp_path)
    rollback_dir.mkdir()
    (rollback_dir / "rollback_snapshot.json").write_text(
        '{"version":"2025.6.14"}\n',
        encoding="utf-8",
    )

    assert store._load_metadata(report_issues=True) is None
    assert any(
        issue.message == "Rollback snapshot metadata is incomplete"
        for issue in tracker.status.issues
    )


def test_rollback_snapshot_metadata_coerces_legacy_non_string_values(tmp_path: Path) -> None:
    store, tracker, rollback_dir = _make_store(tmp_path)
    rollback_dir.mkdir()
    (rollback_dir / "rollback_snapshot.json").write_text(
        '{"version":2025.614,"sha256":12345}\n',
        encoding="utf-8",
    )

    assert store._load_metadata(report_issues=False) == RollbackSnapshotMetadata(
        version="2025.614",
        sha256="12345",
    )
    assert tracker.status.issues == []
