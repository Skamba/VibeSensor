"""Tests for the /api/health endpoint registration."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def _health_client(fake_state):
    """Return ``(client, state, app)`` for health-endpoint tests."""

    from vibesensor.adapters.http import create_router

    fake_state.processing_loop_state.processing_state = "ok"
    fake_state.processing_loop_state.processing_failure_count = 0
    app = FastAPI()
    app.include_router(create_router(fake_state))
    with TestClient(app) as client:
        yield client, fake_state, app


def test_health_route_registered(_health_client):
    """Verify /api/health is registered as a GET route in the API router."""

    _client, _state, app = _health_client
    routes = {r.path: r.methods for r in app.router.routes if hasattr(r, "methods")}
    assert "/api/health" in routes
    assert "GET" in routes["/api/health"]


def test_health_endpoint_response_shape(_health_client):
    """Verify GET /api/health returns typed degradation, data-loss, and persistence state."""

    client, _state, _app = _health_client

    response = client.get("/api/health")

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "ok"
    assert result["startup_state"] == "ready"
    assert result["startup_phase"] == "ready"
    assert result["startup_error"] is None
    assert result["background_task_failures"] == {}
    assert result["db_corruption_detected"] is False
    assert result["db_engine_unhealthy"] is False
    assert result["db_engine_unhealthy_reason"] is None
    assert result["processing_state"] == "ok"
    assert result["processing_failures"] == 0
    assert result["processing_failure_categories"] == {}
    assert result["processing_last_failure"] is None
    assert result["sample_rate_mismatch_count"] == 0
    assert result["frame_size_mismatch_count"] == 0
    assert result["degradation_reasons"] == []
    assert result["subsystems"]["runtime"] == {"status": "ready", "reason_codes": []}
    assert result["subsystems"]["updates"] == {"status": "ready", "reason_codes": []}
    assert result["data_loss"]["tracked_clients"] == 0
    assert result["data_loss"]["buffer_overflow_drops"] == 0
    assert result["persistence"]["write_error"] is None
    assert result["persistence"]["analysis_in_progress"] is False
    assert result["persistence"]["analysis_queue_depth"] == 0
    assert result["persistence"]["analysis_queue_max_depth"] == 0
    assert result["persistence"]["analysis_active_run_id"] is None
    assert result["ingest"]["udp"]["queue_depth"] == 0
    assert result["ingest"]["udp"]["dropped_datagrams"] == 0
    assert result["ingest"]["raw_capture"]["queue_depth"] == 0
    assert result["ingest"]["ws_publish"]["active_connections"] == 0
    assert result["ingest"]["clients"] == []


def test_health_endpoint_degrades_for_data_loss_and_persistence_error(_health_client):
    client, state, _app = _health_client

    state.registry.data_loss_snapshot.return_value = {
        "tracked_clients": 2,
        "affected_clients": 1,
        "frames_dropped": 3,
        "queue_overflow_drops": 0,
        "server_queue_drops": 1,
        "parse_errors": 0,
    }
    state.run_recorder.health_snapshot.return_value = {
        "write_error": "history append_samples failed",
        "analysis_in_progress": True,
        "analysis_queue_depth": 2,
        "analysis_queue_max_depth": 5,
        "analysis_active_run_id": "run-42",
        "analysis_started_at": 1700000000.0,
        "analysis_elapsed_s": 5.0,
        "analysis_queue_oldest_age_s": 8.0,
        "analyzing_run_count": 1,
        "analyzing_oldest_age_s": 12.0,
        "samples_written": 100,
        "samples_dropped": 5,
        "last_completed_run_id": None,
        "last_completed_run_error": None,
    }
    state.processing_loop_state.processing_state = "degraded"
    state.processing_loop_state.processing_failure_count = 2
    state.processing_loop_state.processing_failure_categories = {"compute_all": 2}
    state.processing_loop_state.last_failure_category = "compute_all"
    state.processing_loop_state.last_failure_message = "worker pool failed"
    state.health_state.mark_failed("gps-speed", "gpsd unavailable")
    state.health_state.record_task_failure("metrics-log", "disk write failed")

    response = client.get("/api/health")

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "degraded"
    assert result["degradation_reasons"] == [
        "startup_state:failed",
        "startup_error",
        "background_task_failures",
        "processing_state:degraded",
        "processing_failures",
        "processing_failure:compute_all",
        "frames_dropped",
        "server_queue_drops",
        "persistence_write_error",
        "persistence_samples_dropped",
        "analyzing_runs_present",
    ]
    assert result["startup_phase"] == "gps-speed"
    assert result["startup_error"] == "gpsd unavailable"
    assert result["background_task_failures"] == {"metrics-log": "disk write failed"}
    assert result["subsystems"]["runtime"] == {
        "status": "unhealthy",
        "reason_codes": [
            "startup_not_ready",
            "startup_error",
            "background_task_failures",
        ],
    }
    assert result["subsystems"]["recorder"] == {
        "status": "unhealthy",
        "reason_codes": ["persistence_write_error", "persistence_samples_dropped"],
    }
    assert result["subsystems"]["post_analysis"] == {
        "status": "degraded",
        "reason_codes": ["analyzing_runs_present"],
    }
    assert result["processing_failure_categories"] == {"compute_all": 2}
    assert result["processing_last_failure"] == "worker pool failed"
    assert result["data_loss"]["affected_clients"] == 1
    assert result["persistence"]["write_error"] == "history append_samples failed"
    assert result["persistence"]["analysis_in_progress"] is True
    assert result["persistence"]["analysis_queue_depth"] == 2
    assert result["persistence"]["analysis_queue_max_depth"] == 5
    assert result["persistence"]["analysis_active_run_id"] == "run-42"


def test_health_endpoint_degrades_for_db_corruption(_health_client):
    client, state, _app = _health_client
    state.health_state.mark_db_corrupted("row 7 missing from index")

    response = client.get("/api/health")

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "degraded"
    assert result["db_corruption_detected"] is True
    assert "db_corruption_detected" in result["degradation_reasons"]


def test_health_endpoint_degrades_for_db_engine_failure(_health_client):
    client, state, _app = _health_client
    state.health_state.mark_db_engine_unhealthy(
        "raw_capture_append_timeout",
        "History DB engine operation timed out",
    )

    response = client.get("/api/health")

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "degraded"
    assert result["db_engine_unhealthy"] is True
    assert result["db_engine_unhealthy_reason"] == "raw_capture_append_timeout"
    assert "db_engine_unhealthy" in result["degradation_reasons"]


def test_health_endpoint_warns_for_buffer_overflow_drops(_health_client):
    client, state, _app = _health_client
    state.processor.buffer_overflow_drops.return_value = 4

    response = client.get("/api/health")

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "warn"
    assert result["data_loss"]["buffer_overflow_drops"] == 4
    assert "buffer_overflow_drops" in result["degradation_reasons"]


def test_health_endpoint_validates_through_fastapi_response_field(_health_client):
    """Verify FastAPI can validate the declared /api/health response model."""

    client, _state, app = _health_client
    route = next(r for r in app.router.routes if getattr(r, "path", "") == "/api/health")

    response = client.get("/api/health")
    payload = response.json()
    validated, errors = route.response_field.validate(payload, {}, loc=("response",))

    assert response.status_code == 200
    assert errors == []
    assert payload["status"] == "ok"
    assert payload["startup_state"] == "ready"
    assert payload["data_loss"]["tracked_clients"] == 0
    assert payload["persistence"]["analysis_in_progress"] is False
    assert validated.status == "ok"


def test_health_endpoint_keeps_public_intake_stats_shape_when_worker_pool_is_present(
    _health_client,
):
    client, state, _app = _health_client
    state.processor.intake_stats.return_value = {
        "total_ingested_samples": 10,
        "total_compute_calls": 2,
        "last_compute_duration_s": 0.1,
        "last_compute_all_duration_s": 0.2,
        "last_ingest_duration_s": 0.05,
        "worker_pool": {
            "max_workers": 2,
            "max_queue_size": 2,
            "max_pending_tasks": 4,
            "total_tasks": 7,
            "pending_tasks": 1,
            "queued_tasks": 0,
            "running_tasks": 1,
            "rejected_tasks": 0,
            "total_run_s": 1.5,
            "avg_run_s": 0.75,
            "total_submit_wait_s": 0.2,
            "avg_submit_wait_s": 0.1,
            "default_submit_timeout_s": None,
            "alive": True,
        },
    }

    response = client.get("/api/health")

    assert response.status_code == 200
    result = response.json()
    assert result["intake_stats"] == {
        "total_ingested_samples": 10,
        "total_compute_calls": 2,
        "last_compute_duration_s": 0.1,
        "last_compute_all_duration_s": 0.2,
        "last_ingest_duration_s": 0.05,
    }
    assert "worker_pool" not in result["intake_stats"]
