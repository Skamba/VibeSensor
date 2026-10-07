"""HTTP client tests for the /api/recording routes."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.domain.capture_readiness import (
    CaptureCapabilities,
    CaptureReadiness,
    CaptureReadinessCheck,
)
from vibesensor.recording.status_reporting import RunRecorderStatusSnapshot


def _make_recording_status_snapshot(
    *,
    enabled: bool,
    run_id: str | None,
    samples_written: int,
    start_time_utc: str | None = None,
    elapsed_s: float | None = None,
    samples_dropped: int = 0,
    raw_samples_written: int = 0,
    write_error: str | None = None,
    analysis_in_progress: bool = False,
    last_completed_run_id: str | None = None,
    last_completed_run_error: str | None = None,
    capture_readiness: CaptureReadiness | None = None,
    last_run_id: str | None = None,
    no_data_s: float | None = None,
) -> RunRecorderStatusSnapshot:
    return RunRecorderStatusSnapshot(
        enabled=enabled,
        run_id=run_id,
        write_error=write_error,
        analysis_in_progress=analysis_in_progress,
        start_time_utc=start_time_utc,
        elapsed_s=elapsed_s,
        samples_written=samples_written,
        samples_dropped=samples_dropped,
        raw_samples_written=raw_samples_written,
        last_completed_run_id=last_completed_run_id,
        last_completed_run_error=last_completed_run_error,
        capture_readiness=capture_readiness,
        last_run_id=last_run_id,
        no_data_s=no_data_s,
        no_data_timeout_s=60.0,
    )


@pytest.fixture
def _recording_client(fake_state):
    from vibesensor.web.recording import create_recording_routes

    fake_state.run_recorder.status.return_value = _make_recording_status_snapshot(
        enabled=False,
        run_id=None,
        samples_written=0,
    )
    fake_state.run_recorder.start_recording.return_value = _make_recording_status_snapshot(
        enabled=True,
        run_id="run-abc",
        samples_written=42,
    )
    fake_state.run_recorder.stop_recording.return_value = _make_recording_status_snapshot(
        enabled=False,
        run_id=None,
        samples_written=42,
        analysis_in_progress=True,
        last_run_id="run-abc",
    )
    app = FastAPI()
    app.include_router(create_recording_routes(fake_state.run_recorder))
    with TestClient(app) as client:
        yield client, fake_state


class TestRecordingStatusEndpoint:
    def test_status_serializes_runtime_snapshot(self, _recording_client) -> None:
        client, state = _recording_client
        state.run_recorder.status.return_value = _make_recording_status_snapshot(
            enabled=True,
            run_id="run-123",
            samples_written=84,
            start_time_utc="2026-03-27T12:00:00Z",
            elapsed_s=42.5,
            samples_dropped=3,
            raw_samples_written=67_200,
            analysis_in_progress=True,
            last_completed_run_id="run-122",
            no_data_s=4.5,
        )

        response = client.get("/api/recording/status")

        assert response.status_code == 200
        assert response.json() == {
            "enabled": True,
            "run_id": "run-123",
            "write_error": None,
            "analysis_in_progress": True,
            "start_time_utc": "2026-03-27T12:00:00Z",
            "elapsed_s": 42.5,
            "samples_written": 84,
            "samples_dropped": 3,
            "raw_samples_written": 67_200,
            "last_completed_run_id": "run-122",
            "last_completed_run_error": None,
            "last_stop_reason": None,
            "last_run_id": None,
            "capture_readiness": None,
            "guided_phase": None,
            "guided_phases_completed": [],
            "guided_brake_stops": 0,
            "no_data_s": 4.5,
            "no_data_timeout_s": 60.0,
        }

    def test_status_idle_enabled_false(self, _recording_client) -> None:
        client, _ = _recording_client

        response = client.get("/api/recording/status")

        assert response.status_code == 200
        result = response.json()
        assert result["enabled"] is False
        assert result["run_id"] is None
        assert result["start_time_utc"] is None
        assert result["samples_written"] == 0

    def test_status_serializes_capture_readiness(self, _recording_client) -> None:
        client, state = _recording_client
        state.run_recorder.status.return_value = _make_recording_status_snapshot(
            enabled=False,
            run_id=None,
            samples_written=0,
            capture_readiness=CaptureReadiness(
                is_ready=False,
                checks=(
                    CaptureReadinessCheck(
                        check_key="reference_ready",
                        state="fail",
                        reason_key="speed_source_missing",
                    ),
                    CaptureReadinessCheck(
                        check_key="capture_ready",
                        state="fail",
                        reason_key="capture_blocked",
                        details=(("blocking_check", "reference_ready"),),
                    ),
                ),
                capabilities=CaptureCapabilities(
                    wheel="ok", driveline="missing_final_drive", engine="missing_ratios"
                ),
            ),
        )

        response = client.get("/api/recording/status")

        assert response.status_code == 200
        assert response.json()["capture_readiness"] == {
            "is_ready": False,
            "checks": [
                {
                    "check_key": "reference_ready",
                    "state": "fail",
                    "reason_key": "speed_source_missing",
                    "details": {},
                },
                {
                    "check_key": "capture_ready",
                    "state": "fail",
                    "reason_key": "capture_blocked",
                    "details": {"blocking_check": "reference_ready"},
                },
            ],
            "capabilities": {
                "wheel": "ok",
                "driveline": "missing_final_drive",
                "engine": "missing_ratios",
            },
        }


class TestRecordingStartEndpoint:
    def test_start_returns_running_status(self, _recording_client) -> None:
        client, state = _recording_client

        response = client.post("/api/recording/start")

        assert response.status_code == 200
        assert response.json() == {
            "enabled": True,
            "run_id": "run-abc",
            "write_error": None,
            "analysis_in_progress": False,
            "start_time_utc": None,
            "elapsed_s": None,
            "samples_written": 42,
            "samples_dropped": 0,
            "raw_samples_written": 0,
            "last_completed_run_id": None,
            "last_completed_run_error": None,
            "last_stop_reason": None,
            "last_run_id": None,
            "capture_readiness": None,
            "guided_phase": None,
            "guided_phases_completed": [],
            "guided_brake_stops": 0,
            "no_data_s": None,
            "no_data_timeout_s": 60.0,
        }
        state.run_recorder.start_recording.assert_called_once_with()

    def test_start_when_already_recording_returns_status(self, _recording_client) -> None:
        """start_recording is idempotent — called again it still returns a valid status."""

        client, state = _recording_client
        state.run_recorder.start_recording.return_value = _make_recording_status_snapshot(
            enabled=True,
            run_id="run-abc",
            start_time_utc="2026-03-27T12:01:00Z",
            samples_written=42,
        )

        response = client.post("/api/recording/start")

        assert response.status_code == 200
        assert response.json()["enabled"] is True
        assert "run_id" in response.json()
        assert response.json()["start_time_utc"] == "2026-03-27T12:01:00Z"


class TestRecordingStopEndpoint:
    def test_stop_names_the_stopped_run_while_it_is_analysed(self, _recording_client) -> None:
        client, state = _recording_client

        response = client.post("/api/recording/stop")

        assert response.status_code == 200
        assert response.json() == {
            "enabled": False,
            "run_id": None,
            "write_error": None,
            "analysis_in_progress": True,
            "start_time_utc": None,
            "elapsed_s": None,
            "samples_written": 42,
            "samples_dropped": 0,
            "raw_samples_written": 0,
            "last_completed_run_id": None,
            "last_completed_run_error": None,
            "last_stop_reason": None,
            "last_run_id": "run-abc",
            "capture_readiness": None,
            "guided_phase": None,
            "guided_phases_completed": [],
            "guided_brake_stops": 0,
            "no_data_s": None,
            "no_data_timeout_s": 60.0,
        }
        state.run_recorder.stop_recording.assert_called_once_with()

    def test_stop_when_not_recording_returns_idle_status(self, _recording_client) -> None:
        """stop_recording when not recording is safe — returns idle status."""

        client, state = _recording_client
        state.run_recorder.stop_recording.return_value = _make_recording_status_snapshot(
            enabled=False,
            run_id=None,
            samples_written=0,
        )

        response = client.post("/api/recording/stop")

        assert response.status_code == 200
        assert response.json()["enabled"] is False
        assert response.json()["run_id"] is None


class TestGuidedPhaseEndpoint:
    def test_marks_phase_and_returns_status(self, _recording_client) -> None:
        client, state = _recording_client
        snapshot = replace(
            _make_recording_status_snapshot(enabled=True, run_id="run-abc", samples_written=42),
            guided_phase="brake",
            guided_phases_completed=("sweep", "hold", "coast_down"),
            guided_brake_stops=2,
        )
        state.run_recorder.mark_guided_phase.return_value = snapshot

        response = client.post("/api/recording/guided-phase", json={"phase": "brake"})

        assert response.status_code == 200
        assert response.json()["guided_phase"] == "brake"
        assert response.json()["guided_phases_completed"] == ["sweep", "hold", "coast_down"]
        assert response.json()["guided_brake_stops"] == 2
        state.run_recorder.mark_guided_phase.assert_called_once_with("brake")

    def test_null_phase_ends_the_guided_test(self, _recording_client) -> None:
        client, state = _recording_client
        state.run_recorder.mark_guided_phase.return_value = _make_recording_status_snapshot(
            enabled=True, run_id="run-abc", samples_written=42
        )

        response = client.post("/api/recording/guided-phase", json={"phase": None})

        assert response.status_code == 200
        assert response.json()["guided_phase"] is None
        state.run_recorder.mark_guided_phase.assert_called_once_with(None)

    def test_rejects_unknown_phase(self, _recording_client) -> None:
        client, state = _recording_client

        response = client.post("/api/recording/guided-phase", json={"phase": "launch"})

        assert response.status_code == 422
        state.run_recorder.mark_guided_phase.assert_not_called()
