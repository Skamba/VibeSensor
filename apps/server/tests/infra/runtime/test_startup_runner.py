"""Tests for StartupRunner phase sequencing (#1448)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.startup_runner import StartupRunner
from vibesensor.shared.runtime_failures import BroadcastTickLoopFailure


def _make_runner() -> tuple[StartupRunner, RuntimeHealthState, MagicMock]:
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

    def _start_background_task(task_factory, *, name: str) -> None:
        del name
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
    return runner, health_state, runtime


class TestStartupRunnerPhases:
    """Cover startup phase ordering, success, failure, and UDP-before-background sequencing."""

    @pytest.mark.asyncio
    async def test_phases_tracked_in_order(self) -> None:
        """Health-state phases are set in the expected order."""
        runner, health_state, _ = _make_runner()
        phases_seen: list[str] = []

        original_set_phase = RuntimeHealthState.set_phase

        def recording_set_phase(self_hs: RuntimeHealthState, phase: str) -> None:
            phases_seen.append(phase)
            original_set_phase(self_hs, phase)

        with patch.object(type(health_state), "set_phase", recording_set_phase):
            await runner.run()

        assert phases_seen == [
            "starting",
            "udp_receiver",
            "control_plane",
            "processing-loop",
            "ws-broadcast",
            "metrics-log",
            "gps-speed",
            "obd-speed",
            "update-startup-recover",
        ]

    @pytest.mark.asyncio
    async def test_marks_ready_on_success(self) -> None:
        """Health state is marked ready after all phases complete."""
        runner, health_state, _ = _make_runner()

        await runner.run()

        assert health_state.startup_state == "ready"

    @pytest.mark.asyncio
    async def test_marks_failed_on_exception(self) -> None:
        """Health state records the failing phase on exception."""
        runner, health_state, runtime = _make_runner()
        runtime.control_plane.start = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(RuntimeError, match="boom"):
            await runner.run()

        assert health_state.startup_state == "failed"
        assert health_state.startup_phase == "control_plane"

    @pytest.mark.asyncio
    async def test_ws_broadcast_phase_uses_explicit_restartable_exception_types(self) -> None:
        runner, _, _ = _make_runner()

        await runner.run()

        restartable = runner._task_supervisor.run.call_args_list[1].kwargs["restartable_exceptions"]
        assert restartable == (BroadcastTickLoopFailure,)

    @pytest.mark.asyncio
    async def test_type_error_propagates_without_operational_wrapping(self) -> None:
        runner, health_state, runtime = _make_runner()
        runtime.control_plane.start = AsyncMock(side_effect=TypeError("bad startup wiring"))

        with pytest.raises(TypeError, match="bad startup wiring"):
            await runner.run()

        assert health_state.startup_state != "failed"

    async def test_udp_startup_called_first(self) -> None:
        """UDP receiver starts before background tasks are created."""
        runner, _, _ = _make_runner()
        call_order: list[str] = []

        orig_startup = runner._udp_transport_lifecycle.startup

        async def recording_startup(*a, **kw):
            call_order.append("udp_startup")
            return await orig_startup(*a, **kw)

        runner._udp_transport_lifecycle.startup = recording_startup

        orig_start = runner._background_tasks.start

        def recording_start(*a, **kw):
            call_order.append("background_start")
            return orig_start(*a, **kw)

        runner._background_tasks.start = recording_start

        await runner.run()

        udp_idx = call_order.index("udp_startup")
        bg_idx = call_order.index("background_start")
        assert udp_idx < bg_idx
