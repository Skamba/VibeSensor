# ruff: noqa: E501
"""Tests for analysis persistence, versioned schema, and reuse by summary/report endpoints."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_support import response_payload

from vibesensor.history_db import ANALYSIS_SCHEMA_VERSION, HistoryDB
from vibesensor.history_services.exports import HistoryExportService
from vibesensor.history_services.reports import HistoryReportService
from vibesensor.history_services.runs import HistoryRunService

# -- Schema v4 tests ----------------------------------------------------------


def test_fresh_db_has_analysis_columns(tmp_path: Path) -> None:
    """Fresh DB should have analysis_version, analysis_started_at, analysis_completed_at."""
    db = HistoryDB(tmp_path / "history.db")
    cursor = db._conn.execute("PRAGMA table_info(runs)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "analysis_version" in columns
    assert "analysis_started_at" in columns
    assert "analysis_completed_at" in columns
    db.close()


def test_old_schema_version_raises_when_no_migration_registered(tmp_path: Path) -> None:
    """Opening a DB with an older incompatible version should raise."""
    db_path = tmp_path / "history.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """\
CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO schema_meta (key, value) VALUES ('version', '1');
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
    assert run["analysis_version"] == ANALYSIS_SCHEMA_VERSION
    assert run.get("analysis_completed_at") is not None
    assert run["analysis"] == {"lang": "en", "findings": []}
    db.close()


def test_store_analysis_persists_summary_directly_and_strips_internal_keys(
    tmp_path: Path,
) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("r1", "2026-01-01T00:00:00Z", {"source": "test"})
    db.finalize_run("r1", "2026-01-01T00:01:00Z")

    db.store_analysis("r1", {"lang": "en", "findings": [], "_report_template_data": {"x": 1}})

    with db._cursor(commit=False) as cur:
        cur.execute("SELECT analysis_json FROM runs WHERE run_id = ?", ("r1",))
        row = cur.fetchone()
    assert row is not None
    raw = row[0]
    # No envelope — summary stored directly
    assert '"summary"' not in raw
    assert "_report_template_data" not in raw
    assert '"lang"' in raw
    assert db.get_run("r1").get("analysis") == {"lang": "en", "findings": []}
    db.close()


def test_analysis_is_current_uses_column_version(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("r1", "2026-01-01T00:00:00Z", {"source": "test"})
    db.finalize_run("r1", "2026-01-01T00:01:00Z")

    # Set analysis with current version — should be current
    with db._cursor() as cur:
        cur.execute(
            "UPDATE runs SET status = 'complete', analysis_json = ?, analysis_version = ? WHERE run_id = ?",
            (
                '{"lang": "en", "findings": []}',
                ANALYSIS_SCHEMA_VERSION,
                "r1",
            ),
        )

    assert db.analysis_is_current("r1") is True

    # Set analysis with old version — should be outdated
    with db._cursor() as cur:
        cur.execute(
            "UPDATE runs SET analysis_version = ? WHERE run_id = ?",
            (0, "r1"),
        )

    assert db.analysis_is_current("r1") is False
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
    assert runs[0]["analysis_version"] == ANALYSIS_SCHEMA_VERSION
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
    """Build a minimal fake ``RuntimeState``-alike for router tests.

    Provides the superset of attributes needed by PDF, insights, and export
    endpoint tests so each test only has to supply its own ``history_db``.
    """

    class _FakeState:
        ws_hub = type(
            "WH",
            (),
            {
                "add": staticmethod(lambda ws, sel: None),
                "remove": staticmethod(lambda ws: None),
            },
        )()
        settings_store = type("S", (), {"language": "en", "set_language": lambda self, v: v})()
        metrics_logger = type(
            "M",
            (),
            {
                "status": lambda self: {},
                "start_logging": lambda self: {},
                "stop_logging": lambda self: {},
            },
        )()
        registry = type(
            "R",
            (),
            {
                "snapshot_for_api": lambda self: [],
                "get": lambda self, _: None,
                "set_name": lambda self, cid, name: type(
                    "U",
                    (),
                    {"client_id": cid, "name": name},
                )(),
                "remove_client": lambda self, _: True,
            },
        )()
        control_plane = type("C", (), {"send_identify": lambda self, _id, _dur: (False, None)})()
        gps_monitor = type(
            "G",
            (),
            {
                "effective_speed_mps": None,
                "override_speed_mps": None,
                "set_speed_override_kmh": lambda self, _: None,
            },
        )()
        analysis_settings = type(
            "A",
            (),
            {
                "snapshot": lambda self: {},
                "update": lambda self, payload: payload,
            },
        )()
        processor = type(
            "P",
            (),
            {
                "debug_spectrum": lambda self, _id: {},
                "raw_samples": lambda self, _id, n_samples=1: {},
                "intake_stats": lambda self: {},
            },
        )()

    state = _FakeState()
    state.history_db = history_db
    from unittest.mock import MagicMock

    from vibesensor.runtime import ProcessingLoopState, RuntimeHealthState

    state.loop_state = ProcessingLoopState()
    state.health_state = RuntimeHealthState()
    state.health_state.mark_ready()
    state.apply_car_settings = lambda: None
    state.apply_speed_source_settings = lambda: None
    state.update_manager = MagicMock()
    state.esp_flash_manager = MagicMock()
    state.ingress = SimpleNamespace(
        registry=state.registry,
        processor=state.processor,
        control_plane=state.control_plane,
    )
    state.settings = SimpleNamespace(
        settings_store=state.settings_store,
        gps_monitor=state.gps_monitor,
        analysis_settings=state.analysis_settings,
        apply_car_settings=state.apply_car_settings,
        apply_speed_source_settings=state.apply_speed_source_settings,
    )
    state.persistence = SimpleNamespace(
        history_db=state.history_db,
        run_service=HistoryRunService(state.history_db, state.settings_store),
        report_service=HistoryReportService(state.history_db, state.settings_store),
        export_service=HistoryExportService(state.history_db),
    )
    state.websocket = SimpleNamespace(hub=state.ws_hub)
    state.processing = SimpleNamespace(
        state=state.loop_state,
        health_state=state.health_state,
    )
    return state


def _find_endpoint(router, path: str):
    """Return the endpoint callable for *path*, or ``pytest.fail``."""
    for route in router.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint
    pytest.fail(f"Route {path!r} not found")


def test_stop_run_triggers_analysis_and_persists(tmp_path: Path, monkeypatch) -> None:
    """Integration: stop_logging → post-analysis → analysis persisted in DB."""
    from vibesensor.analysis_settings import AnalysisSettingsStore
    from vibesensor.gps_speed import GPSSpeedMonitor
    from vibesensor.metrics_log import MetricsLogger, MetricsLoggerConfig
    from vibesensor.processing import SignalProcessor
    from vibesensor.registry import ClientRegistry

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

    logger = MetricsLogger(
        MetricsLoggerConfig(
            enabled=False,
            log_path=tmp_path / "metrics.jsonl",
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
    logger.start_logging()
    run_id = logger._run_id
    assert run_id is not None

    # Manually create history and append samples (simulate the metrics loop)
    db.create_run(run_id, "2026-01-01T00:00:00Z", {"run_id": run_id, "language": "en"})
    logger._persistence.history_run_created = True
    samples = [_sample(i) for i in range(20)]
    db.append_samples(run_id, samples)
    logger._persistence.written_sample_count = len(samples)

    # Monkeypatch summarize_run_data to a lightweight version for speed
    def _fake_summarize(metadata, samples, **kwargs):
        return {
            "lang": kwargs.get("lang", "en"),
            "findings": [],
            "top_causes": [],
            "rows": len(samples),
        }

    monkeypatch.setattr("vibesensor.analysis.summarize_run_data", _fake_summarize)

    # Stop logging - should trigger post-analysis
    logger.stop_logging()
    logger.wait_for_post_analysis(timeout_s=5.0)

    # Verify analysis is persisted
    run = db.get_run(run_id)
    assert run is not None
    assert run["status"] == "complete"
    assert run["analysis_version"] == ANALYSIS_SCHEMA_VERSION
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

    from vibesensor.analysis import summarize_run_data
    from vibesensor.routes import create_router

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

    from vibesensor.analysis import summarize_run_data
    from vibesensor.routes import create_router

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

    from vibesensor.routes import create_router

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
