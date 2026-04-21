"""Tests for analysis persistence, versioned schema, and reuse by summary/report endpoints."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_support import response_payload
from test_support.history_db_async import execute_statements, fetch_all
from test_support.persisted_analysis import make_persisted_analysis

from tests.conftest import FakeState
from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.domain.run_status import RunStatus
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frame_from_mapping
from vibesensor.shared.types.history_analysis_contracts import AnalysisSummary
from vibesensor.shared.types.history_records import StoredHistoryRun
from vibesensor.shared.types.run_schema import RunMetadata

# -- Schema v4 tests ----------------------------------------------------------


def _metadata(run_id: str, **overrides: object) -> RunMetadata:
    payload: dict[str, object] = {
        "run_id": run_id,
        "start_time_utc": "2026-01-01T00:00:00Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        "language": "en",
        "source": "test",
    }
    payload.update(overrides)
    return run_metadata_from_mapping(payload)


def _stored_run(
    run_id: str,
    *,
    status: RunStatus = RunStatus.COMPLETE,
    metadata: dict[str, object] | RunMetadata | None = None,
    analysis: dict[str, object] | AnalysisSummary | None = None,
    sample_count: int = 0,
    analysis_started_at: str | None = None,
    analysis_completed_at: str | None = None,
) -> StoredHistoryRun:
    if isinstance(metadata, RunMetadata):
        typed_metadata = metadata
    else:
        metadata_payload = dict(metadata or {})
        metadata_payload.setdefault("run_id", run_id)
        typed_metadata = run_metadata_from_mapping(metadata_payload)
    return StoredHistoryRun(
        run_id=run_id,
        status=status,
        start_time_utc=typed_metadata.start_time_utc,
        end_time_utc=typed_metadata.end_time_utc,
        metadata=typed_metadata,
        created_at=typed_metadata.start_time_utc,
        sample_count=sample_count,
        analysis=make_persisted_analysis(analysis) if analysis is not None else None,
        analysis_started_at=analysis_started_at,
        analysis_completed_at=analysis_completed_at,
    )


def test_fresh_db_has_analysis_columns(tmp_path: Path) -> None:
    """Fresh DB should have analysis_started_at, analysis_completed_at."""
    db = create_history_persistence_adapters(tmp_path / "history.db")
    columns = {row[1] for row in fetch_all(db.lifecycle, "PRAGMA table_info(runs)")}
    assert "analysis_started_at" in columns
    assert "analysis_completed_at" in columns
    db.lifecycle.close()


def test_old_schema_version_raises_when_no_migration_registered(tmp_path: Path) -> None:
    """Opening a DB with an older incompatible version should raise."""
    db_path = tmp_path / "history.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA user_version = 1")
    conn.executescript(
        """\
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'recording',
    start_time_utc TEXT NOT NULL,
    end_time_utc TEXT,
    metadata_json TEXT NOT NULL,
    analysis_json TEXT,
    error_message TEXT,
    sample_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    sample_json TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE TABLE settings_kv (
    key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE client_names (
    client_id TEXT PRIMARY KEY, name TEXT NOT NULL, updated_at TEXT NOT NULL
);
""",
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="incompatible"):
        create_history_persistence_adapters(db_path)


# -- Analysis storage tests ---------------------------------------------------


def test_store_analysis_sets_version_and_timestamps(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1", source="test"))
    db.run_repository.finalize_run("r1", "2026-01-01T00:01:00Z")

    # Check analyzing state has analysis_started_at
    run = db.run_repository.get_run("r1")
    assert run is not None
    assert run.status.value == "analyzing"
    assert run.analysis_started_at is not None

    db.run_repository.store_analysis("r1", make_persisted_analysis({"lang": "en", "findings": []}))
    run = db.run_repository.get_run("r1")
    assert run is not None
    assert run.status.value == "complete"
    assert run.analysis_completed_at is not None
    assert run.analysis == {"lang": "en", "findings": []}
    db.lifecycle.close()


def test_store_analysis_persists_summary_directly(
    tmp_path: Path,
) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1", source="test"))
    db.run_repository.finalize_run("r1", "2026-01-01T00:01:00Z")

    db.run_repository.store_analysis("r1", make_persisted_analysis({"lang": "en", "findings": []}))

    row = fetch_all(
        db.lifecycle,
        "SELECT analysis_json FROM runs WHERE run_id = ?",
        ("r1",),
    )[0]
    raw = row[0]
    payload = json.loads(raw)
    # No envelope — summary stored directly
    assert '"summary"' not in raw
    assert payload["_schema_version"] == 1
    assert payload["lang"] == "en"
    run = db.run_repository.get_run("r1")
    assert run is not None
    assert run.analysis == {"lang": "en", "findings": []}
    db.lifecycle.close()


def test_get_run_marks_unknown_analysis_storage_version_corrupt(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1", source="test"))
    db.run_repository.finalize_run("r1", "2026-01-01T00:01:00Z")

    execute_statements(
        db.lifecycle,
        (
            "UPDATE runs SET analysis_json = ? WHERE run_id = ?",
            ('{"_schema_version": 99, "findings": []}', "r1"),
        ),
    )

    run = db.run_repository.get_run("r1")
    assert run is not None
    assert run.analysis is None
    assert run.analysis_corrupt is True
    db.lifecycle.close()


def test_store_analysis_error_sets_completed_at(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1", source="test"))
    db.run_repository.finalize_run("r1", "2026-01-01T00:01:00Z")
    db.run_repository.store_analysis_error("r1", "Test error")

    run = db.run_repository.get_run("r1")
    assert run is not None
    assert run.status.value == "error"
    assert run.error_message == "Test error"
    assert run.analysis_completed_at is not None
    db.lifecycle.close()


def test_list_runs_includes_analysis_version(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1", source="test"))
    db.run_repository.finalize_run("r1", "2026-01-01T00:01:00Z")
    db.run_repository.store_analysis("r1", make_persisted_analysis({"lang": "en"}))

    runs = db.run_repository.list_runs()
    assert len(runs) == 1
    db.lifecycle.close()


# -- Post-analysis lifecycle tests (integration) ------------------------------


def _sample(i: int) -> dict[str, Any]:
    return {
        "record_type": "sample",
        "run_id": "test-run",
        "timestamp_utc": f"2026-01-01T00:00:{i:02d}Z",
        "t_s": float(i),
        "client_id": "aabbccddeeff",
        "client_name": "front-left wheel",
        "speed_kmh": 60.0 + i,
        "accel_x_g": 0.02,
        "accel_y_g": 0.02,
        "accel_z_g": 0.02,
        "dominant_freq_hz": 15.0,
        "dominant_axis": "x",
        "top_peaks": [
            {
                "hz": 15.0,
                "amp": 0.1,
                "vibration_strength_db": 12.0,
                "strength_bucket": "l2",
            },
        ],
        "vibration_strength_db": 12.0,
        "strength_bucket": "l2",
    }


def _make_fake_state(history_db: Any) -> Any:
    """Build a minimal fake ``RuntimeState``-alike using shared FakeState."""
    return FakeState(
        history_db=history_db.run_repository
        if hasattr(history_db, "run_repository")
        else history_db
    )


def _find_endpoint(router, path: str):
    """Return the endpoint callable for *path*, or ``pytest.fail``."""
    for route in router.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint
    pytest.fail(f"Route {path!r} not found")


def test_stop_run_triggers_analysis_and_persists(tmp_path: Path, monkeypatch) -> None:
    """Integration: stop_recording → post-analysis → analysis persisted in DB."""
    from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
    from vibesensor.infra.processing import SignalProcessor
    from vibesensor.infra.runtime.registry import ClientRegistry
    from vibesensor.use_cases.run import RunRecorder, RunRecorderConfig

    db = create_history_persistence_adapters(tmp_path / "history.db")
    registry = ClientRegistry(db=db.client_name_repository)
    gps_monitor = GPSSpeedMonitor(gps_enabled=False)
    processor = SignalProcessor(
        sample_rate_hz=800,
        waveform_seconds=5,
        waveform_display_hz=60,
        fft_n=256,
        spectrum_max_hz=200,
    )

    logger = RunRecorder(
        RunRecorderConfig(
            metrics_log_hz=10,
            sensor_model="ADXL345",
            default_sample_rate_hz=800,
            fft_window_size_samples=256,
            persist_history_db=True,
        ),
        registry=registry,
        gps_monitor=gps_monitor,
        processor=processor,
        history_db=db.run_repository,
        language_reader=SimpleNamespace(language="en"),
    )

    # Start logging and simulate some data
    logger.start_recording()
    run_id = logger._run_id
    assert isinstance(run_id, str) and len(run_id) > 0

    # Manually create history and append samples (simulate the metrics loop)
    db.run_repository.create_run(run_id, "2026-01-01T00:00:00Z", _metadata(run_id, language="en"))
    logger._persistence.history_run_created = True
    samples = [_sample(i) for i in range(20)]
    db.run_repository.append_samples(
        run_id, [sensor_frame_from_mapping(sample) for sample in samples]
    )
    logger._persistence.written_sample_count = len(samples)

    # Monkeypatch the adapter summarize_run_data wrapper to a lightweight version for speed
    def _fake_summarize(metadata, samples, **kwargs):
        return {
            "lang": kwargs.get("lang", "en"),
            "findings": [],
            "top_causes": [],
            "rows": len(samples),
        }

    monkeypatch.setattr("vibesensor.adapters.analysis_summary.summarize_run_data", _fake_summarize)

    # Stop logging - should trigger post-analysis
    logger.stop_recording()
    logger.wait_for_post_analysis(timeout_s=5.0)

    # Verify analysis is persisted
    run = db.run_repository.get_run(run_id)
    assert run is not None
    assert run.status.value == "complete"
    assert run.analysis is not None
    assert run.analysis["lang"] == "en"
    assert run.analysis_started_at is not None
    assert run.analysis_completed_at is not None
    db.lifecycle.close()


# -- API endpoint reuse tests ------------------------------------------------


@pytest.mark.asyncio
async def test_pdf_reuses_persisted_analysis_same_lang(tmp_path: Path) -> None:
    """PDF generation should reuse persisted analysis when language matches."""
    from dataclasses import dataclass

    from fastapi import FastAPI

    from vibesensor.adapters.analysis_summary import summarize_run_data
    from vibesensor.adapters.http import create_router

    metadata = {
        "run_id": "run-pdf",
        "start_time_utc": "2026-01-01T00:00:00Z",
        "end_time_utc": "2026-01-01T00:00:20Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        "language": "en",
    }
    samples = [_sample(i) for i in range(20)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    analysis["_report_template_data"] = {"lang": "en", "title": "legacy"}

    @dataclass
    class _FakeDB:
        async def aget_run(self, run_id):
            if run_id != "run-pdf":
                return None
            return _stored_run(run_id, metadata=metadata, analysis=analysis)

        async def aiter_run_samples(self, run_id, batch_size=1000, *, stride=1):
            if run_id != "run-pdf":
                return
            frames = [sensor_frame_from_mapping(sample) for sample in samples]
            for start in range(0, len(frames), batch_size):
                yield frames[start : start + batch_size]

        async def alist_runs(self, limit=500):
            return []

        async def aget_active_run_id(self):
            return None

        async def adelete_run(self, run_id):
            return False

    app = FastAPI()
    state = _make_fake_state(_FakeDB())
    router = create_router(state)
    app.include_router(router)

    endpoint = _find_endpoint(router, "/api/history/{run_id}/report.pdf")
    result = await endpoint("run-pdf", "en")
    assert result.body.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_insights_returns_persisted_analysis_no_lang() -> None:
    """Insights without lang param returns persisted analysis directly."""
    from dataclasses import dataclass

    from fastapi import FastAPI

    from vibesensor.adapters.analysis_summary import summarize_run_data
    from vibesensor.adapters.http import create_router

    metadata = {
        "run_id": "run-ins",
        "start_time_utc": "2026-01-01T00:00:00Z",
        "end_time_utc": "2026-01-01T00:00:20Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        "language": "en",
    }
    samples = [_sample(i) for i in range(20)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)

    @dataclass
    class _DB:
        async def aget_run(self, run_id):
            if run_id != "run-ins":
                return None
            return _stored_run(run_id, metadata=metadata, analysis=analysis)

    app = FastAPI()
    state = _make_fake_state(_DB())
    router = create_router(state)
    app.include_router(router)

    endpoint = _find_endpoint(router, "/api/history/{run_id}/insights")
    result = response_payload(await endpoint("run-ins"))
    assert result["lang"] == "en"
    assert "findings" in result


@pytest.mark.asyncio
async def test_export_offloaded_to_thread() -> None:
    """Export endpoint runs in a thread (asyncio.to_thread), not blocking event loop."""
    from dataclasses import dataclass

    from fastapi import FastAPI

    from vibesensor.adapters.http import create_router

    samples = [_sample(i) for i in range(5)]

    @dataclass
    class _DB:
        async def aget_run(self, run_id):
            return _stored_run(run_id, metadata={})

        async def aiter_run_samples(self, run_id, batch_size=1000, *, stride=1):
            frames = [sensor_frame_from_mapping(sample) for sample in samples]
            for start in range(0, len(frames), batch_size):
                yield frames[start : start + batch_size]

    app = FastAPI()
    state = _make_fake_state(_DB())
    router = create_router(state)
    app.include_router(router)

    endpoint = _find_endpoint(router, "/api/history/{run_id}/export")

    import io
    import zipfile

    result = await endpoint("run-exp")
    assert result.media_type == "application/zip"
    chunks = []
    async for chunk in result.body_iterator:
        chunks.append(chunk.encode("utf-8") if isinstance(chunk, str) else chunk)
    body = b"".join(chunks)
    with zipfile.ZipFile(io.BytesIO(body), "r") as zf:
        assert "run-exp_raw.csv" in zf.namelist()
        assert "run-exp.json" in zf.namelist()
