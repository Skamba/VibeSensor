from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.adapters.http.recording import create_recording_routes
from vibesensor.domain import CaptureReadiness, CaptureReadinessCheck
from vibesensor.use_cases.run.status_reporting import RunRecorderStatusSnapshot


def _make_recording_status_snapshot(
    *,
    enabled: bool,
    run_id: str | None,
    samples_written: int,
    start_time_utc: str | None = None,
    samples_dropped: int = 0,
    write_error: str | None = None,
    analysis_in_progress: bool = False,
    last_completed_run_id: str | None = None,
    last_completed_run_error: str | None = None,
    capture_readiness: CaptureReadiness | None = None,
) -> RunRecorderStatusSnapshot:
    return RunRecorderStatusSnapshot(
        enabled=enabled,
        run_id=run_id,
        write_error=write_error,
        analysis_in_progress=analysis_in_progress,
        start_time_utc=start_time_utc,
        samples_written=samples_written,
        samples_dropped=samples_dropped,
        last_completed_run_id=last_completed_run_id,
        last_completed_run_error=last_completed_run_error,
        capture_readiness=capture_readiness,
    )


@pytest.fixture
def recording_client(fake_state):
    app = FastAPI()
    app.include_router(create_recording_routes(fake_state.run_recorder))
    with TestClient(app) as client:
        yield client, fake_state


def test_recording_status_route_returns_serialized_snapshot(recording_client) -> None:
    client, state = recording_client
    state.run_recorder.status.return_value = _make_recording_status_snapshot(
        enabled=True,
        run_id="run-123",
        samples_written=84,
        start_time_utc="2026-03-27T12:00:00Z",
        samples_dropped=3,
        analysis_in_progress=True,
        last_completed_run_id="run-122",
    )

    response = client.get("/api/recording/status")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "run_id": "run-123",
        "write_error": None,
        "analysis_in_progress": True,
        "start_time_utc": "2026-03-27T12:00:00Z",
        "samples_written": 84,
        "samples_dropped": 3,
        "last_completed_run_id": "run-122",
        "last_completed_run_error": None,
        "capture_readiness": None,
    }


def test_recording_status_route_serializes_capture_readiness(recording_client) -> None:
    client, state = recording_client
    state.run_recorder.status.return_value = _make_recording_status_snapshot(
        enabled=False,
        run_id=None,
        samples_written=0,
        capture_readiness=CaptureReadiness(
            is_ready=True,
            checks=(
                CaptureReadinessCheck(
                    check_key="sensors_ready",
                    state="warn",
                    reason_key="limited_sensor_coverage",
                    details=(("live_sensor_count", 1),),
                ),
                CaptureReadinessCheck(
                    check_key="capture_ready",
                    state="warn",
                    reason_key="ready_with_warnings",
                    details=(("warning_check", "sensors_ready"),),
                ),
            ),
        ),
    )

    response = client.get("/api/recording/status")

    assert response.status_code == 200
    assert response.json()["capture_readiness"] == {
        "is_ready": True,
        "checks": [
            {
                "check_key": "sensors_ready",
                "state": "warn",
                "reason_key": "limited_sensor_coverage",
                "details": {"live_sensor_count": 1},
            },
            {
                "check_key": "capture_ready",
                "state": "warn",
                "reason_key": "ready_with_warnings",
                "details": {"warning_check": "sensors_ready"},
            },
        ],
    }


def test_recording_start_route_uses_real_http_routing(recording_client) -> None:
    client, state = recording_client
    state.run_recorder.start_recording.return_value = _make_recording_status_snapshot(
        enabled=True,
        run_id="run-abc",
        start_time_utc="2026-03-27T12:01:00Z",
        samples_written=42,
    )

    response = client.post("/api/recording/start")

    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert response.json()["run_id"] == "run-abc"
    assert response.json()["start_time_utc"] == "2026-03-27T12:01:00Z"
    state.run_recorder.start_recording.assert_called_once_with()


def test_recording_stop_route_uses_real_http_routing(recording_client) -> None:
    client, state = recording_client
    state.run_recorder.stop_recording.return_value = _make_recording_status_snapshot(
        enabled=False,
        run_id=None,
        samples_written=84,
        last_completed_run_id="run-abc",
    )

    response = client.post("/api/recording/stop")

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["last_completed_run_id"] == "run-abc"
    state.run_recorder.stop_recording.assert_called_once_with()
