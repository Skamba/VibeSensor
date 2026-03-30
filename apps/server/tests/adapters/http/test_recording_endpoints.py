"""HTTP client tests for the /api/recording routes."""

from __future__ import annotations

import pytest
from _history_endpoint_helpers import route_endpoint
from test_support import response_payload

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
def _recording_router(fake_state):
    from vibesensor.adapters.http.recording import create_recording_routes

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
        samples_written=0,
    )
    return create_recording_routes(fake_state.run_recorder), fake_state


class TestRecordingStatusEndpoint:
    @pytest.mark.asyncio
    async def test_status_response_shape(self, _recording_router) -> None:
        router, state = _recording_router
        endpoint = route_endpoint(router, "/api/recording/status")

        result = response_payload(await endpoint())

        assert "enabled" in result
        assert "run_id" in result
        assert "write_error" in result
        assert "analysis_in_progress" in result
        assert "start_time_utc" in result
        assert "samples_written" in result
        assert "samples_dropped" in result
        assert "last_completed_run_id" in result
        assert "capture_readiness" in result
        assert "current_file" not in result

    @pytest.mark.asyncio
    async def test_status_idle_enabled_false(self, _recording_router) -> None:
        router, _ = _recording_router
        endpoint = route_endpoint(router, "/api/recording/status")

        result = response_payload(await endpoint())

        assert result["enabled"] is False
        assert result["run_id"] is None
        assert result["start_time_utc"] is None
        assert result["samples_written"] == 0

    @pytest.mark.asyncio
    async def test_status_serializes_capture_readiness(self, _recording_router) -> None:
        router, state = _recording_router
        endpoint = route_endpoint(router, "/api/recording/status")
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
                        reason_key="active_car_missing",
                    ),
                    CaptureReadinessCheck(
                        check_key="capture_ready",
                        state="fail",
                        reason_key="capture_blocked",
                        details=(("blocking_check", "reference_ready"),),
                    ),
                ),
            ),
        )

        result = response_payload(await endpoint())

        assert result["capture_readiness"] == {
            "is_ready": False,
            "checks": [
                {
                    "check_key": "reference_ready",
                    "state": "fail",
                    "reason_key": "active_car_missing",
                    "details": {},
                },
                {
                    "check_key": "capture_ready",
                    "state": "fail",
                    "reason_key": "capture_blocked",
                    "details": {"blocking_check": "reference_ready"},
                },
            ],
        }


class TestRecordingStartEndpoint:
    @pytest.mark.asyncio
    async def test_start_calls_run_recorder(self, _recording_router) -> None:
        router, state = _recording_router
        endpoint = route_endpoint(router, "/api/recording/start")

        result = response_payload(await endpoint())

        state.run_recorder.start_recording.assert_called_once()
        assert result["enabled"] is True
        assert result["run_id"] == "run-abc"

    @pytest.mark.asyncio
    async def test_start_when_already_recording_returns_status(self, _recording_router) -> None:
        """start_recording is idempotent — called again it still returns a valid status."""
        router, state = _recording_router
        endpoint = route_endpoint(router, "/api/recording/start")
        state.run_recorder.start_recording.return_value = _make_recording_status_snapshot(
            enabled=True,
            run_id="run-abc",
            start_time_utc="2026-03-27T12:01:00Z",
            samples_written=42,
        )

        result = response_payload(await endpoint())

        assert result["enabled"] is True
        assert "run_id" in result
        assert result["start_time_utc"] == "2026-03-27T12:01:00Z"


class TestRecordingStopEndpoint:
    @pytest.mark.asyncio
    async def test_stop_calls_run_recorder(self, _recording_router) -> None:
        router, state = _recording_router
        endpoint = route_endpoint(router, "/api/recording/stop")

        result = response_payload(await endpoint())

        state.run_recorder.stop_recording.assert_called_once()
        assert result["enabled"] is False

    @pytest.mark.asyncio
    async def test_stop_when_not_recording_returns_idle_status(self, _recording_router) -> None:
        """stop_recording when not recording is safe — returns idle status."""
        router, state = _recording_router
        endpoint = route_endpoint(router, "/api/recording/stop")
        state.run_recorder.stop_recording.return_value = _make_recording_status_snapshot(
            enabled=False,
            run_id=None,
            samples_written=0,
        )

        result = response_payload(await endpoint())

        assert result["enabled"] is False
        assert result["run_id"] is None
