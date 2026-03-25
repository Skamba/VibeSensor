"""LifecycleManager – async service startup and graceful shutdown.

Owns:
- Background task creation and cancellation
- UDP transport management
- Graceful shutdown sequencing (ingress stop → task cancellation →
  metrics/analysis drain → resource cleanup)
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.task_supervisor import TaskSupervisor, task_failure_message
from vibesensor.infra.runtime.udp_transport_lifecycle import StartUdpReceiver, UdpTransportLifecycle
from vibesensor.shared.constants.ui import UI_PUSH_HZ
from vibesensor.shared.types.payload_types import LiveWsPayload


class LifecycleControlPlane(Protocol):
    async def start(self) -> None: ...

    def close(self) -> None: ...


class LifecycleProcessingLoop(Protocol):
    async def run(self) -> object: ...


class LifecycleWsBroadcast(Protocol):
    def build_payload(self, selected_client: str | None) -> LiveWsPayload: ...

    def on_tick(self) -> None: ...


class LifecycleWsHub(Protocol):
    async def run(
        self,
        hz: int,
        payload_builder: Callable[[str | None], LiveWsPayload],
        on_tick: Callable[[], None] | None = None,
    ) -> None: ...


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
    async def run(self) -> object: ...

    def shutdown_report(self, timeout_s: float = ...) -> LifecycleShutdownReport: ...


class LifecycleGpsMonitor(Protocol):
    async def run(self, *, host: str, port: int) -> object: ...


class LifecycleManagedJobs(Protocol):
    @property
    def job_task(self) -> asyncio.Task[None] | None: ...


class LifecycleUpdateManager(LifecycleManagedJobs, Protocol):
    async def startup_recover(self) -> object: ...


class LifecycleWorkerPool(Protocol):
    def shutdown(self, wait: bool) -> None: ...


class LifecycleHistoryDb(Protocol):
    def close(self) -> None: ...


@dataclass(slots=True)
class LifecycleRuntime:
    """Lifecycle-owned dependency bundle consumed by LifecycleManager."""

    health_state: RuntimeHealthState
    history_db_path: str | Path | None
    udp_data_host: str
    udp_data_port: int
    udp_data_queue_maxsize: int
    gpsd_host: str
    gpsd_port: int
    shutdown_analysis_timeout_s: float
    registry: object
    processor: object
    control_plane: LifecycleControlPlane
    processing_loop: LifecycleProcessingLoop
    ws_hub: LifecycleWsHub
    ws_broadcast: LifecycleWsBroadcast
    run_recorder: LifecycleRunRecorder
    gps_monitor: LifecycleGpsMonitor
    update_manager: LifecycleUpdateManager
    esp_flash_manager: LifecycleManagedJobs
    worker_pool: LifecycleWorkerPool
    history_db: LifecycleHistoryDb


LOGGER = logging.getLogger(__name__)


class LifecycleManager:
    """Manages server startup (UDP receiver, background tasks) and graceful shutdown."""

    __slots__ = (
        "_health_state",
        "_runtime",
        "_task_supervisor",
        "_udp_transport_lifecycle",
        "tasks",
    )

    def __init__(
        self,
        *,
        runtime: LifecycleRuntime,
        start_udp_receiver: StartUdpReceiver,
    ) -> None:
        self._runtime = runtime
        self._health_state = runtime.health_state
        self._task_supervisor = TaskSupervisor(
            health_state=self._health_state,
            logger=LOGGER,
        )
        self._udp_transport_lifecycle = UdpTransportLifecycle(
            start_udp_receiver=start_udp_receiver,
            monitor_task=self._monitor_task,
            logger=LOGGER,
        )
        self.tasks: list[asyncio.Task[object]] = []

    def _monitor_task(self, task: asyncio.Task[object]) -> None:
        task_name = task.get_name()

        def _record_failure(done_task: asyncio.Task[object]) -> None:
            if done_task.cancelled():
                return
            try:
                exc = done_task.exception()
            except asyncio.CancelledError:
                return
            if exc is None:
                return
            message = task_failure_message(exc)
            self._health_state.record_task_failure(task_name, message)
            LOGGER.error("Managed task %s failed: %s", task_name, message, exc_info=exc)

        task.add_done_callback(_record_failure)

    def _start_task(
        self,
        coroutine: Coroutine[object, object, object],
        *,
        name: str,
    ) -> asyncio.Task[object]:
        task = asyncio.create_task(coroutine, name=name)
        self._monitor_task(task)
        return task

    async def _cancel_background_tasks(self, *, timeout_s: float) -> list[asyncio.Task[object]]:
        for task in self.tasks:
            task.cancel()
        if not self.tasks:
            return []
        _done, _pending = await asyncio.wait(self.tasks, timeout=timeout_s)
        if _pending:
            LOGGER.warning(
                "%d background task(s) did not finish within the cancellation "
                "deadline and remain pending: %s",
                len(_pending),
                [task.get_name() for task in _pending],
            )
        self.tasks = [task for task in self.tasks if not task.done()]
        return list(self.tasks)

    @staticmethod
    async def _cancel_managed_tasks(
        tasks: list[asyncio.Task[None]],
        *,
        timeout_s: float,
    ) -> list[asyncio.Task[None]]:
        for task in tasks:
            task.cancel()
        if not tasks:
            return []
        _done, _pending = await asyncio.wait(tasks, timeout=timeout_s)
        if _pending:
            LOGGER.warning(
                "%d managed shutdown task(s) did not finish within the cancellation "
                "deadline and remain pending: %s",
                len(_pending),
                [task.get_name() for task in _pending],
            )
        return [task for task in tasks if not task.done()]

    _LOW_DISK_THRESHOLD_MB = 100

    def _validate_startup(self) -> None:
        """Run lightweight startup precondition checks (warnings only)."""
        try:
            db_path = self._runtime.history_db_path
            data_dir = Path(db_path).parent if db_path else None
        except (AttributeError, TypeError):
            return
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

    async def start(self) -> None:
        """Launch UDP receiver, control plane, and background async tasks."""
        phase = "starting"
        self._health_state.set_phase(phase)
        self._validate_startup()
        try:
            phase = "udp_receiver"
            self._health_state.set_phase(phase)
            await self._udp_transport_lifecycle.startup(
                host=self._runtime.udp_data_host,
                port=self._runtime.udp_data_port,
                registry=self._runtime.registry,
                processor=self._runtime.processor,
                queue_maxsize=self._runtime.udp_data_queue_maxsize,
            )

            phase = "control_plane"
            self._health_state.set_phase(phase)
            await self._runtime.control_plane.start()

            self.tasks = []

            phase = "processing-loop"
            self._health_state.set_phase(phase)
            self.tasks.append(
                self._task_supervisor.start(
                    lambda: self._runtime.processing_loop.run(),
                    name=phase,
                ),
            )

            phase = "ws-broadcast"
            self._health_state.set_phase(phase)
            self.tasks.append(
                self._task_supervisor.start(
                    lambda: self._runtime.ws_hub.run(
                        UI_PUSH_HZ,
                        self._runtime.ws_broadcast.build_payload,
                        on_tick=self._runtime.ws_broadcast.on_tick,
                    ),
                    name=phase,
                ),
            )

            phase = "metrics-log"
            self._health_state.set_phase(phase)
            self.tasks.append(
                self._task_supervisor.start(
                    lambda: self._runtime.run_recorder.run(),
                    name=phase,
                ),
            )

            phase = "gps-speed"
            self._health_state.set_phase(phase)
            self.tasks.append(
                self._task_supervisor.start(
                    lambda: self._runtime.gps_monitor.run(
                        host=self._runtime.gpsd_host,
                        port=self._runtime.gpsd_port,
                    ),
                    name=phase,
                ),
            )

            phase = "update-startup-recover"
            self._health_state.set_phase(phase)
            self.tasks.append(
                self._start_task(
                    self._runtime.update_manager.startup_recover(),
                    name=phase,
                ),
            )
            self._health_state.mark_ready()
        except Exception as exc:
            self._health_state.mark_failed(phase, task_failure_message(exc))
            raise

    async def stop(self) -> None:
        """Graceful shutdown with explicit ingress-stop and metrics-drain phases."""
        try:
            self._runtime.control_plane.close()
        except OSError:
            LOGGER.warning("Error closing control plane", exc_info=True)
        await self._udp_transport_lifecycle.shutdown()

        lingering_background_tasks = await self._cancel_background_tasks(timeout_s=15.0)

        # Cancel any in-progress update or flash jobs so cleanup
        # (e.g. hotspot restore) can run before shutdown completes.
        managed: list[asyncio.Task[None] | None] = [
            self._runtime.update_manager.job_task,
            self._runtime.esp_flash_manager.job_task,
        ]
        active_managed_tasks = [task for task in managed if task is not None and not task.done()]
        lingering_managed_tasks = await self._cancel_managed_tasks(
            active_managed_tasks,
            timeout_s=10.0,
        )

        analysis_timeout_s = self._runtime.shutdown_analysis_timeout_s
        shutdown_report = await asyncio.to_thread(
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
        try:
            await asyncio.to_thread(self._runtime.worker_pool.shutdown, True)
        except Exception:
            LOGGER.warning("Error shutting down worker pool", exc_info=True)
        try:
            self._runtime.history_db.close()
        except Exception:
            LOGGER.warning("Error closing history DB", exc_info=True)
        self.tasks = [task for task in self.tasks if not task.done()]
        lingering_task_names = [
            *(task.get_name() for task in lingering_background_tasks if not task.done()),
            *(task.get_name() for task in lingering_managed_tasks if not task.done()),
        ]
        if lingering_task_names:
            LOGGER.warning(
                "Runtime lifecycle stop completed with lingering tasks: %s",
                lingering_task_names,
            )
            return
        LOGGER.info("Runtime lifecycle stopped cleanly.")
