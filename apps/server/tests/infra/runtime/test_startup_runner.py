"""Tests for StartupRunner phase sequencing (#1448)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.startup_runner import StartupRunner


def _make_runner() -> tuple[StartupRunner, RuntimeHealthState, MagicMock, list[str]]:
    """Build a minimal StartupRunner with mock collaborators."""
    health_state = RuntimeHealthState()

    runtime = MagicMock()
    runtime.udp_data_host = "0.0.0.0"
    runtime.udp_data_port = 9000
    runtime.udp_data_queue_maxsize = 64
    runtime.gpsd_host = "127.0.0.1"
    runtime.gpsd_port = 2947
    runtime.control_plane.start = AsyncMock()
    runtime.processing_loop.run = AsyncMock()
    runtime.ws_hub.run = AsyncMock()
    runtime.ws_broadcast.build_payload = MagicMock()
    runtime.ws_broadcast.on_tick = MagicMock()
    runtime.run_recorder.run = AsyncMock()
    runtime.gps_monitor.run = AsyncMock()
    runtime.obd_runner.run = AsyncMock()
    runtime.update_manager.startup_recover = AsyncMock()

    task_supervisor = MagicMock()
    task_supervisor.run = AsyncMock()

    started_names: list[str] = []

    def _start_background_task(task_factory, *, name: str) -> None:
        started_names.append(name)
        task_factory().close()

    background_tasks = MagicMock()
    background_tasks.start = MagicMock(side_effect=_start_background_task)

    udp_transport = MagicMock()
    udp_transport.startup = AsyncMock()

    runner = StartupRunner(
        runtime=runtime,
        health_state=health_state,
        task_supervisor=task_supervisor,
        background_tasks=background_tasks,
        udp_transport_lifecycle=udp_transport,
    )
    return runner, health_state, runtime, started_names


class TestStartupRunnerPhases:
    """Cover startup success/failure outcomes without pinning internal phase plumbing."""

    @pytest.mark.asyncio
    async def test_marks_ready_on_success_and_starts_runtime_tasks(self) -> None:
        """Successful startup reaches ready state and starts the expected background tasks."""
        runner, health_state, _runtime, started_names = _make_runner()
        await runner.run()

        assert health_state.startup_state == "ready"
        assert started_names == [
            "processing-loop",
            "ws-broadcast",
            "metrics-log",
            "gps-speed",
            "obd-speed",
            "update-startup-recover",
        ]

    @pytest.mark.asyncio
    async def test_marks_failed_on_exception(self) -> None:
        """Health state records the failing phase on exception."""
        runner, health_state, runtime, _started_names = _make_runner()
        runtime.control_plane.start = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            await runner.run()

        assert health_state.startup_state == "failed"
        assert health_state.startup_phase == "control_plane"

    @pytest.mark.asyncio
    async def test_type_error_propagates_without_operational_wrapping(self) -> None:
        runner, health_state, runtime, _started_names = _make_runner()
        runtime.control_plane.start = AsyncMock(side_effect=TypeError("bad startup wiring"))
        with pytest.raises(TypeError, match="bad startup wiring"):
            await runner.run()

        assert health_state.startup_state != "failed"
