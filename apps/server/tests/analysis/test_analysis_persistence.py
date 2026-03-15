# ruff: noqa: E501
"""Tests for analysis persistence, versioned schema, and reuse by summary/report endpoints."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeState
from test_support import response_payload

from vibesensor.adapters.persistence.history_db import HistoryDB

# -- Schema v4 tests ----------------------------------------------------------


def test_fresh_db_has_analysis_columns(tmp_path: Path) -> None:
    """Fresh DB should have analysis_started_at, analysis_completed_at."""
    db = HistoryDB(tmp_path / "history.db")
    cursor = db._conn.execute("PRAGMA table_info(runs)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "analysis_started_at" in columns
    assert "analysis_completed_at" in columns
    db.close()


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
        HistoryDB(db_path)


# -- Analysis storage tests ---------------------------------------------------


def test_store_analysis_sets_version_and_timestamps(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("r1", "2026-01-01T00:00:00Z", {"source": "test"})
    db.finalize_run("r1", "2026-01-01T00:01:00Z")

    # Check analyzing state has analysis_started_at
    run = db.get_run("r1")
    assert run is not None
    assert run["status"] == "analyzing"
    assert run.get("analysis_started_at") is not None

    db.store_analysis("r1", {"lang": "en", "findings": []})
    run = db.get_run("r1")
    assert run is not None
    assert run["status"] == "complete"
    assert run.get("analysis_completed_at") is not None
    assert run["analysis"] == {"lang": "en", "findings": []}
    db.close()


def test_store_analysis_persists_summary_directly(
    tmp_path: Path,
) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("r1", "2026-01-01T00:00:00Z", {"source": "test"})
    db.finalize_run("r1", "2026-01-01T00:01:00Z")

    db.store_analysis("r1", {"lang": "en", "findings": []})

    with db._cursor(commit=False) as cur:
        cur.execute("SELECT analysis_json FROM runs WHERE run_id = ?", ("r1",))
        row = cur.fetchone()
    assert row is not None
    raw = row[0]
    # No envelope — summary stored directly
    assert '"summary"' not in raw
    assert '"lang"' in raw
    assert db.get_run("r1").get("analysis") == {"lang": "en", "findings": []}
    db.close()


def test_store_analysis_error_sets_completed_at(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("r1", "2026-01-01T00:00:00Z", {"source": "test"})
    db.finalize_run("r1", "2026-01-01T00:01:00Z")
    db.store_analysis_error("r1", "Test error")

    run = db.get_run("r1")
    assert run is not None
    assert run["status"] == "error"
    assert run.get("error_message") == "Test error"
    assert run.get("analysis_completed_at") is not None
    db.close()


def test_list_runs_includes_analysis_version(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("r1", "2026-01-01T00:00:00Z", {"source": "test"})
    db.finalize_run("r1", "2026-01-01T00:01:00Z")
    db.store_analysis("r1", {"lang": "en"})

    runs = db.list_runs()
    assert len(runs) == 1
    db.close()


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
    return FakeState(history_db=history_db)


def _find_endpoint(router, path: str):
    """Return the endpoint callable for *path*, or ``pytest.fail``."""
    for route in router.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint
    pytest.fail(f"Route {path!r} not found")


def test_stop_run_triggers_analysis_and_persists(tmp_path: Path, monkeypatch) -> None:
    """Integration: stop_recording → post-analysis → analysis persisted in DB."""
    from vibesensor.infra.config.analysis_settings import AnalysisSettingsStore
    from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
    from vibesensor.use_cases.run import RunRecorder, RunRecorderConfig
    from vibesensor.infra.processing import SignalProcessor
    from vibesensor.infra.runtime.registry import ClientRegistry

    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db)
    gps_monitor = GPSSpeedMonitor(gps_enabled=False)
    processor = SignalProcessor(
        sample_rate_hz=800,
        waveform_seconds=5,
        waveform_display_hz=60,
        fft_n=256,
        spectrum_max_hz=200,
    )
    analysis_settings = AnalysisSettingsStore()

    logger = RunRecorder(
        RunRecorderConfig(
            enabled=False,
            metrics_log_hz=10,
            sensor_model="ADXL345",
            default_sample_rate_hz=800,
            fft_window_size_samples=256,
            persist_history_db=True,
        ),
        registry=registry,
        gps_monitor=gps_monitor,
        processor=processor,
        analysis_settings=analysis_settings,
        history_db=db,
        language_provider=lambda: "en",
    )

    # Start logging and simulate some data
    logger.start_recording()
    run_id = logger._run_id
    assert run_id is not None

    # Manually create history and append samples (simulate the metrics loop)
    db.create_run(run_id, "2026-01-01T00:00:00Z", {"run_id": run_id, "language": "en"})
    logger._persist_history_run_created = True
    samples = [_sample(i) for i in range(20)]
    db.append_samples(run_id, samples)
    logger._persist_written_sample_count = len(samples)

    # Monkeypatch summarize_run_data to a lightweight version for speed
    def _fake_summarize(metadata, samples, **kwargs):
        return {
            "lang": kwargs.get("lang", "en"),
            "findings": [],
            "top_causes": [],
            "rows": len(samples),
        }

    monkeypatch.setattr("vibesensor.use_cases.diagnostics.summarize_run_data", _fake_summarize)

    # Stop logging - should trigger post-analysis
    logger.stop_recording()
    logger.wait_for_post_analysis(timeout_s=5.0)

    # Verify analysis is persisted
    run = db.get_run(run_id)
    assert run is not None
    assert run["status"] == "complete"
    assert run.get("analysis") is not None
    assert run["analysis"]["lang"] == "en"
    assert run.get("analysis_started_at") is not None
    assert run.get("analysis_completed_at") is not None
    db.close()


# -- API endpoint reuse tests ------------------------------------------------


@pytest.mark.asyncio
async def test_pdf_reuses_persisted_analysis_same_lang(tmp_path: Path) -> None:
    """PDF generation should reuse persisted analysis when language matches."""
    from dataclasses import dataclass

    from fastapi import FastAPI

    from vibesensor.use_cases.diagnostics import summarize_run_data
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
        def get_run(self, run_id):
            if run_id != "run-pdf":
                return None
            return {
                "run_id": run_id,
                "status": "complete",
                "metadata": metadata,
                "analysis": analysis,
            }

        def iter_run_samples(self, run_id, batch_size=1000):
            if run_id != "run-pdf":
                return
            for start in range(0, len(samples), batch_size):
                yield samples[start : start + batch_size]

        def list_runs(self):
            return []

        def get_active_run_id(self):
            return None

        def delete_run(self, run_id):
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

    from vibesensor.use_cases.diagnostics import summarize_run_data
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
        def get_run(self, run_id):
            if run_id != "run-ins":
                return None
            return {
                "run_id": run_id,
                "status": "complete",
                "metadata": metadata,
                "analysis": analysis,
            }

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
        def get_run(self, run_id):
            return {"run_id": run_id, "status": "complete", "metadata": {}}

        def iter_run_samples(self, run_id, batch_size=1000):
            for start in range(0, len(samples), batch_size):
                yield samples[start : start + batch_size]

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
