"""LifecycleManager – async service startup and graceful shutdown.

Owns:
- Background task creation and cancellation
- UDP transport management
- Graceful shutdown sequencing (ingress stop → task cancellation →
  metrics/analysis drain → resource cleanup)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
from collections.abc import Coroutine
from pathlib import Path
from typing import TYPE_CHECKING

from ..udp_data_rx import start_udp_data_receiver

if TYPE_CHECKING:
    from ..config import AppConfig
    from ..esp_flash_manager import EspFlashManager
    from ..metrics_log import MetricsLogger
    from ..update.manager import UpdateManager
    from .state import (
        RuntimeIngressSubsystem,
        RuntimePersistenceSubsystem,
        RuntimeProcessingSubsystem,
        RuntimeSettingsSubsystem,
        RuntimeWebsocketSubsystem,
    )

LOGGER = logging.getLogger(__name__)


class LifecycleManager:
    """Manages server startup (UDP receiver, background tasks) and graceful shutdown."""

    __slots__ = (
        "_config",
        "_data_consumer_task",
        "_data_transport",
        "_esp_flash_manager",
        "_health_state",
        "_ingress",
        "_metrics_logger",
        "_persistence",
        "_processing",
        "_settings",
        "_update_manager",
        "_websocket",
        "tasks",
    )

    def __init__(
        self,
        *,
        config: AppConfig,
        ingress: RuntimeIngressSubsystem,
        settings: RuntimeSettingsSubsystem,
        metrics_logger: MetricsLogger,
        persistence: RuntimePersistenceSubsystem,
        update_manager: UpdateManager,
        esp_flash_manager: EspFlashManager,
        processing: RuntimeProcessingSubsystem,
        websocket: RuntimeWebsocketSubsystem,
    ) -> None:
        self._config = config
        self._ingress = ingress
        self._settings = settings
        self._metrics_logger = metrics_logger
        self._persistence = persistence
        self._update_manager = update_manager
        self._esp_flash_manager = esp_flash_manager
        self._processing = processing
        self._websocket = websocket
        self._health_state = processing.health_state
        self.tasks: list[asyncio.Task[object]] = []
        self._data_transport: asyncio.DatagramTransport | None = None
        self._data_consumer_task: asyncio.Task[object] | None = None

    @staticmethod
    def _task_failure_message(exc: BaseException) -> str:
        message = str(exc).strip() or exc.__class__.__name__
        return message[:240]

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
            message = self._task_failure_message(exc)
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

    _LOW_DISK_THRESHOLD_MB = 100

    def _validate_startup(self) -> None:
        """Run lightweight startup precondition checks (warnings only)."""
        try:
            db_path = self._config.logging.history_db_path
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
            self._data_transport, self._data_consumer_task = await start_udp_data_receiver(
                host=self._config.udp.data_host,
                port=self._config.udp.data_port,
                registry=self._ingress.registry,
                processor=self._ingress.processor,
                queue_maxsize=self._config.udp.data_queue_maxsize,
            )

            phase = "control_plane"
            self._health_state.set_phase(phase)
            await self._ingress.control_plane.start()

            self.tasks = []

            phase = "processing-loop"
            self._health_state.set_phase(phase)
            self.tasks.append(self._start_task(self._processing.loop.run(), name=phase))

            phase = "ws-broadcast"
            self._health_state.set_phase(phase)
            self.tasks.append(
                self._start_task(
                    self._websocket.hub.run(
                        self._config.processing.ui_push_hz,
                        self._websocket.broadcast.build_payload,
                        on_tick=self._websocket.broadcast.on_tick,
                    ),
                    name=phase,
                ),
            )

            phase = "metrics-log"
            self._health_state.set_phase(phase)
            self.tasks.append(self._start_task(self._metrics_logger.run(), name=phase))

            phase = "gps-speed"
            self._health_state.set_phase(phase)
            self.tasks.append(
                self._start_task(
                    self._settings.gps_monitor.run(
                        host=self._config.gps.gpsd_host,
                        port=self._config.gps.gpsd_port,
                    ),
                    name=phase,
                ),
            )

            phase = "update-startup-recover"
            self._health_state.set_phase(phase)
            self.tasks.append(
                self._start_task(
                    self._update_manager.startup_recover(),
                    name=phase,
                ),
            )
            self._health_state.mark_ready()
        except Exception as exc:
            self._health_state.mark_failed(phase, self._task_failure_message(exc))
            raise

    async def stop(self) -> None:
        """Graceful shutdown with explicit ingress-stop and metrics-drain phases."""
        try:
            self._ingress.control_plane.close()
        except OSError:
            LOGGER.warning("Error closing control plane", exc_info=True)
        try:
            if self._data_transport is not None:
                self._data_transport.close()
                self._data_transport = None
        except OSError:
            LOGGER.warning("Error closing data transport", exc_info=True)
        if self._data_consumer_task is not None:
            self._data_consumer_task.cancel()
            await asyncio.gather(self._data_consumer_task, return_exceptions=True)
            self._data_consumer_task = None

        for task in self.tasks:
            task.cancel()
        # Wait up to 15 s for tasks to respond to cancellation.
        if self.tasks:
            _done, _pending = await asyncio.wait(self.tasks, timeout=15.0)
            if _pending:
                LOGGER.warning(
                    "%d background task(s) did not finish within the cancellation "
                    "deadline and will be abandoned: %s",
                    len(_pending),
                    [t.get_name() for t in _pending],
                )
        self.tasks.clear()

        # Cancel any in-progress update or flash jobs so cleanup
        # (e.g. hotspot restore) can run before shutdown completes.
        managed: list[asyncio.Task[None] | None] = [
            self._update_manager.job_task,
            self._esp_flash_manager.job_task,
        ]
        for managed_task in managed:
            if managed_task is not None:
                managed_task.cancel()
        for managed_task in managed:
            if managed_task is not None and not managed_task.done():
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(asyncio.shield(managed_task), timeout=10.0)

        analysis_timeout_s = self._config.logging.shutdown_analysis_timeout_s
        shutdown_report = await asyncio.to_thread(
            self._metrics_logger.shutdown_report,
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
            await asyncio.to_thread(self._ingress.worker_pool.shutdown, True)
        except Exception:
            LOGGER.warning("Error shutting down worker pool", exc_info=True)
        try:
            self._persistence.history_db.close()
        except Exception:
            LOGGER.warning("Error closing history DB", exc_info=True)
        LOGGER.info("Runtime lifecycle stopped cleanly.")
