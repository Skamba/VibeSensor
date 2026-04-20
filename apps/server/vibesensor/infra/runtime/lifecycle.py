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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vibesensor.infra.runtime.background_task_coordinator import BackgroundTaskCoordinator
from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.shutdown_sequence import (
    LifecycleShutdownIssue,
    LifecycleShutdownSequence,
)
from vibesensor.infra.runtime.task_supervisor import TaskSupervisor
from vibesensor.infra.runtime.udp_transport_lifecycle import StartUdpReceiver, UdpTransportLifecycle
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


class LifecycleObdRunner(Protocol):
    async def run(self) -> object: ...


class LifecycleManagedJobs(Protocol):
    @property
    def job_task(self) -> asyncio.Task[None] | None: ...


class LifecycleUpdateManager(LifecycleManagedJobs, Protocol):
    async def startup_recover(self) -> object: ...


class LifecycleWorkerPool(Protocol):
    def shutdown(self, wait: bool) -> None: ...


class LifecycleHistoryDb(Protocol):
    def close(self) -> object: ...


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
    obd_runner: LifecycleObdRunner
    update_manager: LifecycleUpdateManager
    esp_flash_manager: LifecycleManagedJobs
    worker_pool: LifecycleWorkerPool
    history_db: LifecycleHistoryDb


LOGGER = logging.getLogger(__name__)


class LifecycleManager:
    """Manages server startup (UDP receiver, background tasks) and graceful shutdown."""

    __slots__ = (
        "_background_tasks",
        "_health_state",
        "_runtime",
        "_shutdown_sequence",
        "_task_supervisor",
        "_udp_transport_lifecycle",
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
        self._background_tasks = BackgroundTaskCoordinator(
            logger=LOGGER,
        )
        self._udp_transport_lifecycle = UdpTransportLifecycle(
            start_udp_receiver=start_udp_receiver,
            start_background_task=lambda task_factory: self._background_tasks.start(
                lambda: self._task_supervisor.run(
                    task_factory,
                    name="udp-data-consumer",
                ),
                name="udp-data-consumer",
            ),
            logger=LOGGER,
        )
        self._shutdown_sequence = LifecycleShutdownSequence(
            runtime=runtime,
            background_tasks=self._background_tasks,
            udp_transport_lifecycle=self._udp_transport_lifecycle,
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

    async def start(self) -> None:
        """Launch UDP receiver, control plane, and background async tasks."""
        from vibesensor.infra.runtime.startup_runner import StartupRunner

        self._validate_startup()
        await self._background_tasks.open()
        runner = StartupRunner(
            runtime=self._runtime,
            health_state=self._health_state,
            task_supervisor=self._task_supervisor,
            background_tasks=self._background_tasks,
            udp_transport_lifecycle=self._udp_transport_lifecycle,
        )
        await runner.run()

    async def stop(self) -> None:
        """Graceful shutdown with explicit ingress-stop and metrics-drain phases."""
        shutdown = await self._shutdown_sequence.run()
        self._report_shutdown_issues(shutdown.issues)
        self._report_lingering_tasks(
            list(shutdown.lingering_background),
            list(shutdown.lingering_managed),
        )

    def _report_shutdown_issues(self, issues: tuple[LifecycleShutdownIssue, ...]) -> None:
        for issue in issues:
            LOGGER.warning(
                issue.message,
                exc_info=(
                    type(issue.exception),
                    issue.exception,
                    issue.exception.__traceback__,
                ),
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
