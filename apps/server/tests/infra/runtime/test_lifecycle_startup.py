"""LifecycleManager startup phase sequencing (#1448) and UDP transport start/cleanup."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.lifecycle import LifecycleManager, LifecycleRuntime
from vibesensor.ingest.diagnostics import IngestDiagnosticsCollector


def _make_runtime(started: list[str]) -> LifecycleRuntime:
    """Build a lifecycle runtime whose services record their start order and then park."""

    def _parking(name: str) -> AsyncMock:
        async def _run(*args, **kwargs) -> None:
            started.append(name)
            await asyncio.Event().wait()

        return AsyncMock(side_effect=_run)

    async def _recover() -> None:
        started.append("update-startup-recover")

    return LifecycleRuntime(
        health_state=RuntimeHealthState(),
        history_db_path=None,
        udp_data_host="0.0.0.0",
        udp_data_port=9000,
        shutdown_analysis_timeout_s=5.0,
        registry=MagicMock(),
        processor=MagicMock(),
        ingest_diagnostics=IngestDiagnosticsCollector(),
        control_plane=MagicMock(start=AsyncMock(), close=MagicMock()),
        processing_loop=MagicMock(run=_parking("processing-loop")),
        ws_broadcaster=MagicMock(run=_parking("ws-broadcast")),
        run_recorder=MagicMock(
            run=_parking("metrics-log"),
            shutdown_report=MagicMock(return_value=SimpleNamespace(completed=True)),
        ),
        gps_monitor=MagicMock(run=_parking("gps-speed")),
        obd_runner=MagicMock(run=_parking("obd-speed")),
        update_manager=MagicMock(startup_recover=AsyncMock(side_effect=_recover), job_task=None),
        esp_flash_manager=MagicMock(job_task=None),
        history_db=MagicMock(),
    )


async def _settle(started: list[str], expected: int) -> None:
    for _ in range(50):
        if len(started) >= expected:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"only started {started}")


class TestStartupPhases:
    """Cover startup success/failure outcomes without pinning internal phase plumbing."""

    @pytest.mark.asyncio
    async def test_marks_ready_on_success_and_starts_runtime_tasks(self) -> None:
        """Successful startup reaches ready state and starts the expected background tasks."""
        started: list[str] = []
        runtime = _make_runtime(started)
        lifecycle = LifecycleManager(
            runtime=runtime,
            start_udp_receiver=AsyncMock(return_value=(None, None)),
        )
        await lifecycle.start()
        try:
            await _settle(started, 6)
            assert runtime.health_state.startup_state == "ready"
            assert started == [
                "processing-loop",
                "ws-broadcast",
                "metrics-log",
                "gps-speed",
                "obd-speed",
                "update-startup-recover",
            ]
        finally:
            await lifecycle.stop()

    @pytest.mark.asyncio
    async def test_stop_immediately_after_start_does_not_hang(self) -> None:
        """Shutdown before the background services first run must not wedge close()."""
        started: list[str] = []
        lifecycle = LifecycleManager(
            runtime=_make_runtime(started),
            start_udp_receiver=AsyncMock(return_value=(None, None)),
        )
        await lifecycle.start()

        async with asyncio.timeout(5.0):
            await lifecycle.stop()

        assert lifecycle.tasks == []

    @pytest.mark.asyncio
    async def test_marks_failed_on_exception(self) -> None:
        """Health state records the failing phase on exception."""
        runtime = _make_runtime([])
        runtime.control_plane.start = AsyncMock(side_effect=RuntimeError("boom"))
        lifecycle = LifecycleManager(
            runtime=runtime,
            start_udp_receiver=AsyncMock(return_value=(None, None)),
        )
        try:
            with pytest.raises(RuntimeError, match="boom"):
                await lifecycle.start()

            assert runtime.health_state.startup_state == "failed"
            assert runtime.health_state.startup_phase == "control_plane"
        finally:
            await lifecycle.stop()

    @pytest.mark.asyncio
    async def test_type_error_propagates_without_operational_wrapping(self) -> None:
        runtime = _make_runtime([])
        runtime.control_plane.start = AsyncMock(side_effect=TypeError("bad startup wiring"))
        lifecycle = LifecycleManager(
            runtime=runtime,
            start_udp_receiver=AsyncMock(return_value=(None, None)),
        )
        try:
            with pytest.raises(TypeError, match="bad startup wiring"):
                await lifecycle.start()

            assert runtime.health_state.startup_state != "failed"
        finally:
            await lifecycle.stop()


class _FakeConsumer:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def process_queue(self) -> None:
        self.started.set()
        await asyncio.Event().wait()


class TestUdpTransport:
    """UDP receiver startup wiring and shutdown cleanup."""

    @pytest.mark.asyncio
    async def test_startup_passes_runtime_wiring_and_runs_consumer_task(self) -> None:
        runtime = _make_runtime([])
        consumer = _FakeConsumer()
        start_udp_receiver = AsyncMock(return_value=(MagicMock(), consumer))
        lifecycle = LifecycleManager(runtime=runtime, start_udp_receiver=start_udp_receiver)

        await lifecycle.start()
        try:
            await asyncio.wait_for(consumer.started.wait(), timeout=1.0)
            assert "udp-data-consumer" in lifecycle.tasks
            start_udp_receiver.assert_awaited_once_with(
                host="0.0.0.0",
                port=9000,
                registry=runtime.registry,
                processor=runtime.processor,
                raw_capture_sink=runtime.run_recorder.raw_capture,
                ingest_diagnostics=runtime.ingest_diagnostics,
            )
        finally:
            await lifecycle.stop()

    @pytest.mark.asyncio
    async def test_stop_closes_transport_once(self) -> None:
        transport = MagicMock()
        started: list[str] = []
        lifecycle = LifecycleManager(
            runtime=_make_runtime(started),
            start_udp_receiver=AsyncMock(return_value=(transport, None)),
        )

        await lifecycle.start()
        await _settle(started, 6)
        await lifecycle.stop()
        await lifecycle.stop()

        transport.close.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_stop_logs_transport_close_error(self, caplog: pytest.LogCaptureFixture) -> None:
        transport = MagicMock()
        transport.close.side_effect = OSError("close boom")
        started: list[str] = []
        lifecycle = LifecycleManager(
            runtime=_make_runtime(started),
            start_udp_receiver=AsyncMock(return_value=(transport, None)),
        )
        await lifecycle.start()
        await _settle(started, 6)

        with caplog.at_level(logging.WARNING):
            await lifecycle.stop()

        assert "Error closing data transport" in caplog.text

    @pytest.mark.asyncio
    async def test_stop_without_start_is_noop_for_transport(self) -> None:
        start_udp_receiver = AsyncMock()
        lifecycle = LifecycleManager(
            runtime=_make_runtime([]),
            start_udp_receiver=start_udp_receiver,
        )

        await lifecycle.stop()

        start_udp_receiver.assert_not_awaited()
