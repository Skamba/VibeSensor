from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from test_support.history_db_async import execute_statements as _execute_statements
from test_support.history_db_lifecycle import (
    build_history_db,
    create_completed_run,
    create_recording_run,
)

from vibesensor.shared.types.whole_run_analysis import (
    WHOLE_RUN_ARTIFACT_STORAGE_DIR_NAME,
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunWindowPolicy,
)


def _manifest(run_id: str) -> WholeRunArtifactManifest:
    return WholeRunArtifactManifest(
        run_id=run_id,
        relative_dir=f"{WHOLE_RUN_ARTIFACT_STORAGE_DIR_NAME}/{run_id}",
        window_policy=WholeRunWindowPolicy(
            sample_rate_hz=800,
            window_size_samples=2048,
            stride_samples=200,
            overlap_samples=1848,
            feature_interval_s=0.25,
        ),
        total_window_count=4,
        artifacts=(
            WholeRunArtifactFile(
                artifact_key="window-spectra",
                relative_path="window-spectra.bin",
                file_format="bin",
                record_count=4,
            ),
            WholeRunArtifactFile(
                artifact_key="order-traces",
                relative_path="orders/order-traces.jsonl",
                file_format="jsonl",
                record_count=7,
            ),
        ),
        created_at="2025-01-01T00:00:00Z",
    )


def _store_whole_run_artifacts(
    db,
    run_id: str,
    manifest: WholeRunArtifactManifest,
) -> WholeRunArtifactManifest | None:
    return db.run_repository._run_sync(
        db.run_repository.astore_whole_run_artifacts(
            run_id,
            manifest,
            artifact_contents={
                "window-spectra": b"spec-data",
                "order-traces": b'{"window_index":0}\n',
            },
        )
    )


def test_whole_run_artifact_round_trip_persists_manifest_and_bytes(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    create_recording_run(db, "run-artifacts")
    manifest = _manifest("run-artifacts")

    stored_manifest = _store_whole_run_artifacts(db, "run-artifacts", manifest)

    assert stored_manifest == manifest
    stored_run = db.run_repository.get_run("run-artifacts")
    assert stored_run is not None
    assert stored_run.whole_run_artifact_manifest == manifest
    loaded_manifest = db.run_repository._run_sync(
        db.run_repository.aget_whole_run_artifact_manifest("run-artifacts")
    )
    assert loaded_manifest == manifest
    loaded_bytes = db.run_repository._run_sync(
        db.run_repository.aload_whole_run_artifact("run-artifacts", "window-spectra")
    )
    assert loaded_bytes == b"spec-data"


def test_legacy_run_without_whole_run_sidecar_remains_readable(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    create_completed_run(db, "run-legacy")

    stored_run = db.run_repository.get_run("run-legacy")

    assert stored_run is not None
    assert stored_run.whole_run_artifact_manifest is None
    assert (
        db.run_repository._run_sync(
            db.run_repository.aget_whole_run_artifact_manifest("run-legacy")
        )
        is None
    )


def test_delete_run_removes_whole_run_artifacts(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    create_recording_run(db, "run-delete")
    manifest = _manifest("run-delete")

    stored_manifest = _store_whole_run_artifacts(db, "run-delete", manifest)

    assert stored_manifest is not None
    artifact_dir = tmp_path / WHOLE_RUN_ARTIFACT_STORAGE_DIR_NAME / "run-delete"
    assert artifact_dir.exists()

    db.run_repository.delete_run("run-delete")

    assert not artifact_dir.exists()


def test_store_whole_run_artifacts_cleans_up_when_run_is_missing(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    manifest = _manifest("run-missing")

    stored_manifest = _store_whole_run_artifacts(db, "run-missing", manifest)

    assert stored_manifest is None
    artifact_dir = tmp_path / WHOLE_RUN_ARTIFACT_STORAGE_DIR_NAME / "run-missing"
    assert not artifact_dir.exists()


def test_prune_terminal_runs_removes_whole_run_artifacts(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    create_completed_run(db, "run-prune")
    manifest = _manifest("run-prune")

    stored_manifest = _store_whole_run_artifacts(db, "run-prune", manifest)

    assert stored_manifest is not None
    artifact_dir = tmp_path / WHOLE_RUN_ARTIFACT_STORAGE_DIR_NAME / "run-prune"
    assert artifact_dir.exists()

    old_timestamp = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    _execute_statements(
        db.lifecycle,
        (
            "UPDATE runs SET analysis_completed_at = ?, end_time_utc = ? WHERE run_id = ?",
            (old_timestamp, old_timestamp, "run-prune"),
        ),
    )

    db.run_repository.prune_terminal_runs_older_than_days(1)

    assert not artifact_dir.exists()
