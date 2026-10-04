"""Shared builders for HistoryDB lifecycle tests."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from test_support.core import canonicalize_run_context_metadata
from test_support.persisted_analysis import make_persisted_analysis
from vibesensor.domain.run_status import RunStatus
from vibesensor.history.history_db import HistoryDB
from vibesensor.history.records import StoredHistoryRun
from vibesensor.recording.raw_capture import RawCaptureManifest
from vibesensor.recording.run_metadata import run_metadata_from_mapping
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.settings.settings_snapshot import SettingsSnapshotPayload
from vibesensor.summary.contracts import AnalysisSummary


def build_history_db(tmp_path: Path) -> HistoryDB:
    return HistoryDB(tmp_path / "history.db")


def make_stored_run(
    metadata: RunMetadata,
    *,
    sample_count: int = 0,
    raw_capture_manifest: RawCaptureManifest | None = None,
) -> StoredHistoryRun:
    """An ``analyzing`` stored run for fake ``HistoryDB.get_run`` implementations."""
    return StoredHistoryRun(
        run_id=metadata.run_id,
        status=RunStatus.ANALYZING,
        start_time_utc=metadata.start_time_utc,
        end_time_utc=metadata.end_time_utc,
        metadata=metadata,
        created_at=metadata.start_time_utc,
        sample_count=sample_count,
        raw_capture_manifest=raw_capture_manifest,
    )


def run_samples(db: HistoryDB, run_id: str) -> list[SensorFrame]:
    """Every stored sample of *run_id*, flattened from ``iter_run_samples`` batches."""
    return [frame for batch in db.iter_run_samples(run_id) for frame in batch]


def make_run_metadata(run_id: str, **overrides: object) -> RunMetadata:
    payload: dict[str, object] = {
        "run_id": run_id,
        "start_time_utc": "2026-01-01T00:00:00Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        "source": "test",
    }
    payload.update(overrides)
    return run_metadata_from_mapping(canonicalize_run_context_metadata(payload))


def make_analysis_summary(run_id: str, **overrides: object) -> AnalysisSummary:
    payload: dict[str, object] = {
        "run_id": run_id,
        "findings": [],
        "top_causes": [],
        "warnings": [],
    }
    payload.update(overrides)
    return cast(AnalysisSummary, payload)


def make_settings_snapshot() -> SettingsSnapshotPayload:
    return {
        "cars": [],
        "activeCarId": None,
        "speedSource": "gps",
        "manualSpeedKph": None,
        "staleTimeoutS": 10.0,
        "language": "en",
        "speedUnit": "kmh",
        "timeZone": None,
        "sensorsByMac": {},
    }


def create_recording_run(
    db: HistoryDB,
    run_id: str,
    *,
    started_at: str = "2026-01-01T00:00:00Z",
    metadata: RunMetadata | None = None,
    case_id: str | None = None,
    **metadata_overrides: object,
) -> RunMetadata:
    metadata_obj = metadata or make_run_metadata(run_id, **metadata_overrides)
    db.create_run(run_id, started_at, metadata_obj, case_id=case_id)
    return metadata_obj


def create_analyzing_run(
    db: HistoryDB,
    run_id: str,
    *,
    started_at: str = "2026-01-01T00:00:00Z",
    finalized_at: str = "2026-01-01T00:01:00Z",
    metadata: RunMetadata | None = None,
    case_id: str | None = None,
    **metadata_overrides: object,
) -> RunMetadata:
    metadata_obj = create_recording_run(
        db,
        run_id,
        started_at=started_at,
        metadata=metadata,
        **metadata_overrides,
    )
    db.finalize_run(run_id, finalized_at, metadata=metadata_obj, case_id=case_id)
    return metadata_obj


def create_completed_run(
    db: HistoryDB,
    run_id: str,
    *,
    started_at: str = "2026-01-01T00:00:00Z",
    finalized_at: str = "2026-01-01T00:01:00Z",
    metadata: RunMetadata | None = None,
    analysis: AnalysisSummary | None = None,
    case_id: str | None = None,
    metadata_overrides: dict[str, object] | None = None,
    analysis_overrides: dict[str, object] | None = None,
) -> AnalysisSummary:
    create_analyzing_run(
        db,
        run_id,
        started_at=started_at,
        finalized_at=finalized_at,
        metadata=metadata,
        case_id=case_id,
        **(metadata_overrides or {}),
    )
    analysis_obj = analysis or make_analysis_summary(run_id, **(analysis_overrides or {}))
    db.store_analysis(run_id, make_persisted_analysis(analysis_obj))
    return analysis_obj


def create_error_run(
    db: HistoryDB,
    run_id: str,
    *,
    started_at: str = "2026-01-01T00:00:00Z",
    finalized_at: str = "2026-01-01T00:01:00Z",
    error_message: str = "failed",
    metadata: RunMetadata | None = None,
    metadata_overrides: dict[str, object] | None = None,
) -> None:
    create_analyzing_run(
        db,
        run_id,
        started_at=started_at,
        finalized_at=finalized_at,
        metadata=metadata,
        **(metadata_overrides or {}),
    )
    db.store_analysis_error(run_id, error_message)
