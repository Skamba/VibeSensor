"""Tests for the /api/recording/* endpoint response shapes and behavior."""

from __future__ import annotations

import pytest
from test_support import response_payload

_RECORDING_STATUS_DICT = {
    "enabled": True,
    "run_id": "run-abc",
    "write_error": None,
    "analysis_in_progress": False,
    "samples_written": 42,
    "samples_dropped": 0,
    "last_completed_run_id": None,
    "last_completed_run_error": None,
}

_IDLE_STATUS_DICT = {
    "enabled": False,
    "run_id": None,
    "write_error": None,
    "analysis_in_progress": False,
    "samples_written": 0,
    "samples_dropped": 0,
    "last_completed_run_id": None,
    "last_completed_run_error": None,
}


def _find_endpoint(router, path: str):
    for route in router.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint
    return None


@pytest.fixture
def _recording_router(fake_state):
    from vibesensor.adapters.http.recording import create_recording_routes

    fake_state.run_recorder.status.return_value = _IDLE_STATUS_DICT
    fake_state.run_recorder.start_recording.return_value = _RECORDING_STATUS_DICT
    fake_state.run_recorder.stop_recording.return_value = _IDLE_STATUS_DICT
    return create_recording_routes(fake_state.run_recorder), fake_state


class TestRecordingStatusEndpoint:
    @pytest.mark.asyncio
    async def test_status_response_shape(self, _recording_router) -> None:
        router, state = _recording_router
        endpoint = _find_endpoint(router, "/api/recording/status")
        assert endpoint is not None

        result = response_payload(await endpoint())

        assert "enabled" in result
        assert "run_id" in result
        assert "write_error" in result
        assert "analysis_in_progress" in result
        assert "samples_written" in result
        assert "samples_dropped" in result
        assert "last_completed_run_id" in result
        assert "current_file" not in result

    @pytest.mark.asyncio
    async def test_status_idle_enabled_false(self, _recording_router) -> None:
        router, _ = _recording_router
        endpoint = _find_endpoint(router, "/api/recording/status")

        result = response_payload(await endpoint())

        assert result["enabled"] is False
        assert result["run_id"] is None
        assert result["samples_written"] == 0


class TestRecordingStartEndpoint:
    @pytest.mark.asyncio
    async def test_start_calls_run_recorder(self, _recording_router) -> None:
        router, state = _recording_router
        endpoint = _find_endpoint(router, "/api/recording/start")
        assert endpoint is not None

        result = response_payload(await endpoint())

        state.run_recorder.start_recording.assert_called_once()
        assert result["enabled"] is True
        assert result["run_id"] == "run-abc"

    @pytest.mark.asyncio
    async def test_start_when_already_recording_returns_status(self, _recording_router) -> None:
        """start_recording is idempotent — called again it still returns a valid status."""
        router, state = _recording_router
        endpoint = _find_endpoint(router, "/api/recording/start")
        state.run_recorder.start_recording.return_value = _RECORDING_STATUS_DICT

        result = response_payload(await endpoint())

        assert result["enabled"] is True
        assert "run_id" in result


class TestRecordingStopEndpoint:
    @pytest.mark.asyncio
    async def test_stop_calls_run_recorder(self, _recording_router) -> None:
        router, state = _recording_router
        endpoint = _find_endpoint(router, "/api/recording/stop")
        assert endpoint is not None

        result = response_payload(await endpoint())

        state.run_recorder.stop_recording.assert_called_once()
        assert result["enabled"] is False

    @pytest.mark.asyncio
    async def test_stop_when_not_recording_returns_idle_status(self, _recording_router) -> None:
        """stop_recording when not recording is safe — returns idle status."""
        router, state = _recording_router
        endpoint = _find_endpoint(router, "/api/recording/stop")
        state.run_recorder.stop_recording.return_value = _IDLE_STATUS_DICT

        result = response_payload(await endpoint())

        assert result["enabled"] is False
        assert result["run_id"] is None
