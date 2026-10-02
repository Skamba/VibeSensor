"""LifecycleManager – async service startup and graceful shutdown.

Owns:
- Named startup phases with health-state reporting
- Background task creation (via ``BackgroundTaskCoordinator`` +
  ``TaskSupervisor``) and cancellation
- UDP data-transport startup and cleanup
- Graceful shutdown sequencing (ingress stop → task cancellation →
  managed-job cancellation → metrics/analysis drain → resource cleanup)

The protocols below describe collaborators implemented in outer layers
(adapters / use cases) that infra may not import directly.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sqlite3
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import anyio

from vibesensor.infra.runtime.background_tasks import (
    BackgroundTaskCoordinator,
    RestartableExceptions,
    TaskSupervisor,
    task_failure_message,
)
from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.shared.ingest_diagnostics import IngestDiagnosticsCollector
from vibesensor.shared.runtime_failures import BroadcastTickLoopFailure

if TYPE_CHECKING:
    from vibesensor.infra.processing import SignalProcessor
    from vibesensor.infra.runtime.processing_loop import ProcessingLoop
    from vibesensor.infra.runtime.registry import ClientRegistry

__all__ = [
    "LifecycleManager",
    "LifecycleRuntime",
    "StartUdpReceiver",
    "cancel_managed_jobs",
]


class LifecycleControlPlane(Protocol):
    async def start(self) -> None: ...

    def close(self) -> None: ...


class LifecycleWsBroadcaster(Protocol):
    async def run(self) -> None: ...


class LifecycleShutdownReport(Protocol):
    @property
    def completed(self) -> bool: ...

    @property
    def analysis_queue_depth(self) -> int: ...

    @property
    def analysis_active_run_id(self) -> str | None: ...

    @property
    def analysis_queue_oldest_age_s(self) -> float | None: ...

    @property
    def active_run_id_before_stop(self) -> str | None: ...

    @property
    def write_error(self) -> str | None: ...


class LifecycleRunRecorder(Protocol):
    @property
    def raw_capture(self) -> object: ...

    async def run(self) -> object: ...

    def shutdown_report(self, timeout_s: float = ...) -> LifecycleShutdownReport: ...


class LifecycleGpsMonitor(Protocol):
    async def run(self) -> object: ...


class LifecycleObdRunner(Protocol):
    async def run(self) -> object: ...


class LifecycleManagedJobs(Protocol):
    @property
    def job_task(self) -> asyncio.Task[None] | None: ...


class LifecycleUpdateManager(LifecycleManagedJobs, Protocol):
    async def startup_recover(self) -> object: ...


class LifecycleHistoryDb(Protocol):
    def close(self) -> None: ...


class UdpQueueConsumer(Protocol):
    async def process_queue(self) -> None: ...


StartUdpReceiver = Callable[
    ...,
    Awaitable[tuple[asyncio.DatagramTransport | None, UdpQueueConsumer | None]],
]


@dataclass(slots=True)
class LifecycleRuntime:
    """Lifecycle-owned dependency bundle consumed by LifecycleManager."""

    health_state: RuntimeHealthState
    history_db_path: str | Path | None
    udp_data_host: str
    udp_data_port: int
    registry: ClientRegistry
    processor: SignalProcessor
    ingest_diagnostics: IngestDiagnosticsCollector
    control_plane: LifecycleControlPlane
    processing_loop: ProcessingLoop
    ws_broadcaster: LifecycleWsBroadcaster
    run_recorder: LifecycleRunRecorder
    gps_monitor: LifecycleGpsMonitor
    obd_runner: LifecycleObdRunner
    update_manager: LifecycleUpdateManager
    esp_flash_manager: LifecycleManagedJobs
    history_db: LifecycleHistoryDb
    shutdown_analysis_timeout_s: float = 30.0
    """How long shutdown waits for queued post-analysis before giving up."""


LOGGER = logging.getLogger(__name__)

_BACKGROUND_CANCEL_TIMEOUT_S = 15.0
_MANAGED_JOB_CANCEL_TIMEOUT_S = 10.0


async def cancel_managed_jobs(
    sources: Sequence[LifecycleManagedJobs],
    *,
    timeout_s: float,
) -> list[asyncio.Task[None]]:
    """Cancel the active managed job tasks (update, flash); return any that outlive *timeout_s*."""
    tasks = [s.job_task for s in sources if s.job_task is not None and not s.job_task.done()]
    for task in tasks:
        task.cancel()
    if not tasks:
        return []
    _done, pending = await asyncio.wait(tasks, timeout=timeout_s)
    if pending:
        LOGGER.warning(
            "%d managed shutdown task(s) did not finish within the cancellation "
            "deadline and remain pending: %s",
            len(pending),
            [task.get_name() for task in pending],
        )
    return [task for task in tasks if not task.done()]


StartupPhase = tuple[str, Callable[[], Awaitable[None]]]


class LifecycleManager:
    """Manages server startup (UDP receiver, background tasks) and graceful shutdown."""

    __slots__ = (
        "_background_tasks",
        "_data_transport",
        "_health_state",
        "_runtime",
        "_start_udp_receiver",
        "_task_supervisor",
    )

    def __init__(
        self,
        *,
        runtime: LifecycleRuntime,
        start_udp_receiver: StartUdpReceiver,
    ) -> None:
        self._runtime = runtime
        self._health_state = runtime.health_state
        self._start_udp_receiver = start_udp_receiver
        self._data_transport: asyncio.DatagramTransport | None = None
        self._task_supervisor = TaskSupervisor(
            health_state=self._health_state,
            logger=LOGGER,
        )
        self._background_tasks = BackgroundTaskCoordinator(
            logger=LOGGER,
        )

    @property
    def tasks(self) -> list[str]:
        return self._background_tasks.tasks

    _LOW_DISK_THRESHOLD_MB = 100

    def _validate_startup(self) -> None:
        """Run lightweight startup precondition checks (warnings only)."""
        db_path = self._runtime.history_db_path
        data_dir = Path(db_path).parent if isinstance(db_path, str | Path) else None
        if data_dir is None or str(db_path) == ":memory:":
            return
        try:
            free_mb = shutil.disk_usage(data_dir).free // (1024 * 1024)
            if free_mb < self._LOW_DISK_THRESHOLD_MB:
                msg = f"low disk space: {free_mb}MB free on {data_dir}"
                self._health_state.startup_warnings.append(msg)
                LOGGER.warning("Startup check: %s", msg)
        except OSError:
            LOGGER.debug(
                "Startup check: unable to query disk usage for %s",
                data_dir,
            )

    # -- startup ---------------------------------------------------------------

    async def start(self) -> None:
        """Launch UDP receiver, control plane, and background async tasks."""
        self._validate_startup()
        await self._background_tasks.open()
        await self._run_startup_phases()

    async def _run_startup_phases(self) -> None:
        """Execute the named startup phases in order with health-state tracking."""
        phase_name = "starting"
        self._health_state.set_phase(phase_name)
        try:
            for phase_name, run_phase in self._startup_phases():
                self._health_state.set_phase(phase_name)
                await run_phase()
            self._health_state.mark_ready()
        except (OSError, RuntimeError) as exc:
            self._health_state.mark_failed(phase_name, task_failure_message(exc))
            raise

    def _startup_phases(self) -> list[StartupPhase]:
        r = self._runtime
        return [
            ("udp_receiver", self._start_udp_transport),
            ("control_plane", r.control_plane.start),
            (
                "processing-loop",
                lambda: self._start_supervised(lambda: r.processing_loop.run(), "processing-loop"),
            ),
            (
                "ws-broadcast",
                lambda: self._start_supervised(
                    lambda: r.ws_broadcaster.run(),
                    "ws-broadcast",
                    restartable_exceptions=(BroadcastTickLoopFailure,),
                ),
            ),
            (
                "metrics-log",
                lambda: self._start_supervised(lambda: r.run_recorder.run(), "metrics-log"),
            ),
            (
                "gps-speed",
                lambda: self._start_supervised(
                    lambda: r.gps_monitor.run(),
                    "gps-speed",
                ),
            ),
            (
                "obd-speed",
                lambda: self._start_supervised(lambda: r.obd_runner.run(), "obd-speed"),
            ),
            ("update-startup-recover", self._start_update_recovery),
        ]

    async def _start_udp_transport(self) -> None:
        r = self._runtime
        self._data_transport, consumer = await self._start_udp_receiver(
            host=r.udp_data_host,
            port=r.udp_data_port,
            registry=r.registry,
            processor=r.processor,
            raw_capture_sink=r.run_recorder.raw_capture,
            ingest_diagnostics=r.ingest_diagnostics,
        )
        if consumer is not None:
            await self._start_supervised(consumer.process_queue, "udp-data-consumer")

    async def _start_supervised(
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

    # -- shutdown --------------------------------------------------------------

    async def stop(self) -> None:
        """Graceful shutdown with explicit ingress-stop and metrics-drain phases.

        Resource-close failures are collected and logged after the whole
        sequence has run so one failing step never skips the later ones.
        """
        r = self._runtime
        issues: list[tuple[str, Exception]] = []
        try:
            r.control_plane.close()
        except OSError as exc:
            issues.append(("Error closing control plane", exc))
        self._close_udp_transport()
        lingering_background = await self._background_tasks.cancel_all(
            timeout_s=_BACKGROUND_CANCEL_TIMEOUT_S,
        )
        lingering_managed = await cancel_managed_jobs(
            [r.update_manager, r.esp_flash_manager],
            timeout_s=_MANAGED_JOB_CANCEL_TIMEOUT_S,
        )
        await self._drain_analysis()
        try:
            await anyio.to_thread.run_sync(r.history_db.close)
        except (sqlite3.Error, OSError) as exc:
            issues.append(("Error closing history DB", exc))
        if not lingering_background:
            await self._background_tasks.close()
        for message, issue in issues:
            LOGGER.warning(message, exc_info=(type(issue), issue, issue.__traceback__))
        self._report_lingering_tasks(lingering_background, lingering_managed)

    def _close_udp_transport(self) -> None:
        try:
            if self._data_transport is not None:
                self._data_transport.close()
                self._data_transport = None
        except OSError:
            LOGGER.warning("Error closing data transport", exc_info=True)

    async def _drain_analysis(self) -> None:
        analysis_timeout_s = self._runtime.shutdown_analysis_timeout_s
        shutdown_report = await anyio.to_thread.run_sync(
            self._runtime.run_recorder.shutdown_report,
            analysis_timeout_s,
        )
        if not shutdown_report.completed:
            LOGGER.warning(
                "Post-analysis did not finish within %.1fs on shutdown; "
                "results for the last run may be lost. active_run_before_stop=%s "
                "queue_depth=%d active_run=%s oldest_queue_age_s=%s write_error=%s",
                analysis_timeout_s,
                shutdown_report.active_run_id_before_stop,
                shutdown_report.analysis_queue_depth,
                shutdown_report.analysis_active_run_id,
                shutdown_report.analysis_queue_oldest_age_s,
                shutdown_report.write_error,
            )

    def _report_lingering_tasks(
        self,
        lingering_background: list[str],
        lingering_managed: list[asyncio.Task[None]],
    ) -> None:
        lingering_task_names = [
            *lingering_background,
            *(task.get_name() for task in lingering_managed if not task.done()),
        ]
        if lingering_task_names:
            LOGGER.warning(
                "Runtime lifecycle stop completed with lingering tasks: %s",
                lingering_task_names,
            )
            return
        LOGGER.info("Runtime lifecycle stopped cleanly.")
