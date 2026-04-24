"""Startup phase runner for LifecycleManager.

Owns the named startup phase sequence and health-state reporting
previously inlined in ``LifecycleManager.start()``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import anyio
from opentelemetry.trace import SpanKind

from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.task_supervisor import task_failure_message
from vibesensor.shared.runtime_failures import BroadcastTickLoopFailure
from vibesensor.shared.tracing import mark_span_error, start_span

if TYPE_CHECKING:
    from vibesensor.infra.runtime.background_task_coordinator import BackgroundTaskCoordinator
    from vibesensor.infra.runtime.lifecycle import (
        LifecycleRuntime,
    )
    from vibesensor.infra.runtime.task_supervisor import RestartableExceptions, TaskSupervisor
    from vibesensor.infra.runtime.udp_transport_lifecycle import UdpTransportLifecycle


@dataclass(frozen=True, slots=True)
class StartupPhase:
    """A single named startup phase."""

    name: str
    run: Callable[[], Awaitable[None]]


class StartupRunner:
    """Execute named startup phases with health-state tracking."""

    __slots__ = (
        "_background_tasks",
        "_health_state",
        "_runtime",
        "_task_supervisor",
        "_udp_transport_lifecycle",
    )

    def __init__(
        self,
        *,
        runtime: LifecycleRuntime,
        health_state: RuntimeHealthState,
        task_supervisor: TaskSupervisor,
        background_tasks: BackgroundTaskCoordinator,
        udp_transport_lifecycle: UdpTransportLifecycle,
    ) -> None:
        self._runtime = runtime
        self._health_state = health_state
        self._task_supervisor = task_supervisor
        self._background_tasks = background_tasks
        self._udp_transport_lifecycle = udp_transport_lifecycle

    async def run(self) -> None:
        """Execute all startup phases in order."""
        phase_name = "starting"
        self._health_state.set_phase(phase_name)
        cancelled_exc_class = anyio.get_cancelled_exc_class()
        try:
            for phase in self._phases():
                phase_name = phase.name
                self._health_state.set_phase(phase_name)
                with start_span(
                    __name__,
                    "runtime.startup.phase",
                    kind=SpanKind.INTERNAL,
                    attributes={"vibesensor.phase": phase_name},
                ) as span:
                    try:
                        await phase.run()
                    except cancelled_exc_class:
                        span.set_attribute("vibesensor.cancelled", True)
                        raise
                    except (OSError, RuntimeError) as exc:
                        mark_span_error(span, exc)
                        raise
            self._health_state.mark_ready()
        except (OSError, RuntimeError) as exc:
            self._health_state.mark_failed(phase_name, task_failure_message(exc))
            raise

    def _phases(self) -> list[StartupPhase]:
        from vibesensor.shared.constants.ui import UI_PUSH_HZ

        r = self._runtime
        return [
            StartupPhase("udp_receiver", self._start_udp_receiver),
            StartupPhase("control_plane", r.control_plane.start),
            StartupPhase(
                "processing-loop",
                lambda: self._start_background(lambda: r.processing_loop.run(), "processing-loop"),
            ),
            StartupPhase(
                "ws-broadcast",
                lambda: self._start_background(
                    lambda: r.ws_hub.run(
                        UI_PUSH_HZ,
                        r.ws_broadcast.build_payload,
                        on_tick=r.ws_broadcast.on_tick,
                        metrics_recorder=lambda connection_count, duration_s: (
                            r.ingest_diagnostics.note_ws_publish(
                                connection_count=connection_count,
                                duration_s=duration_s,
                            )
                        ),
                    ),
                    "ws-broadcast",
                    restartable_exceptions=(BroadcastTickLoopFailure,),
                ),
            ),
            StartupPhase(
                "metrics-log",
                lambda: self._start_background(lambda: r.run_recorder.run(), "metrics-log"),
            ),
            StartupPhase(
                "gps-speed",
                lambda: self._start_background(
                    lambda: r.gps_monitor.run(
                        host=r.gpsd_host,
                        port=r.gpsd_port,
                    ),
                    "gps-speed",
                ),
            ),
            StartupPhase(
                "obd-speed",
                lambda: self._start_background(lambda: r.obd_runner.run(), "obd-speed"),
            ),
            StartupPhase(
                "update-startup-recover",
                self._start_update_recovery,
            ),
        ]

    async def _start_udp_receiver(self) -> None:
        await self._udp_transport_lifecycle.startup(
            host=self._runtime.udp_data_host,
            port=self._runtime.udp_data_port,
            registry=self._runtime.registry,
            processor=self._runtime.processor,
            raw_capture_sink=self._runtime.run_recorder,
            queue_maxsize=self._runtime.udp_data_queue_maxsize,
            ingest_diagnostics=self._runtime.ingest_diagnostics,
        )

    async def _start_background(
        self,
        coro_factory: Callable[[], Awaitable[object]],
        name: str,
        *,
        restartable_exceptions: RestartableExceptions = (),
    ) -> None:
        self._background_tasks.start(
            lambda: self._task_supervisor.run(
                coro_factory,
                name=name,
                restartable_exceptions=restartable_exceptions,
            ),
            name=name,
        )

    async def _start_update_recovery(self) -> None:
        self._background_tasks.start(
            self._runtime.update_manager.startup_recover,
            name="update-startup-recover",
        )
