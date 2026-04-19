"""Shared builders for HistoryDB lifecycle tests."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from test_support.core import canonicalize_run_context_metadata
from test_support.persisted_analysis import make_persisted_analysis
from vibesensor.adapters.persistence.history_db import HistoryDB
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.types.history_analysis_contracts import AnalysisSummary
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.settings_snapshot import SettingsSnapshotPayload


def build_history_db(tmp_path: Path) -> HistoryDB:
    return HistoryDB(tmp_path / "history.db")


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
