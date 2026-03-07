"""LifecycleManager – async service startup and graceful shutdown.

Owns:
- Background task creation and cancellation
- UDP transport management
- Graceful shutdown sequencing (analysis wait → resource cleanup)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from ..udp_data_rx import start_udp_data_receiver

if TYPE_CHECKING:
    from ..config import AppConfig
    from ..esp_flash_manager import EspFlashManager
    from ..gps_speed import GPSSpeedMonitor
    from ..history_db import HistoryDB
    from ..metrics_log import MetricsLogger
    from ..processing import SignalProcessor
    from ..registry import ClientRegistry
    from ..udp_control_tx import UDPControlPlane
    from ..update.manager import UpdateManager
    from ..worker_pool import WorkerPool
    from ..ws_hub import WebSocketHub
    from .processing_loop import ProcessingLoop
    from .ws_broadcast import WsBroadcastService

LOGGER = logging.getLogger(__name__)


class LifecycleManager:
    """Manages server startup (UDP receiver, background tasks) and graceful shutdown."""

    __slots__ = (
        "_config",
        "_registry",
        "_processor",
        "_control_plane",
        "_ws_hub",
        "_gps_monitor",
        "_metrics_logger",
        "_update_manager",
        "_esp_flash_manager",
        "_history_db",
        "_worker_pool",
        "_processing_loop",
        "_ws_broadcast",
        "tasks",
        "_data_transport",
        "_data_consumer_task",
    )

    def __init__(
        self,
        *,
        config: AppConfig,
        registry: ClientRegistry,
        processor: SignalProcessor,
        control_plane: UDPControlPlane,
        ws_hub: WebSocketHub,
        gps_monitor: GPSSpeedMonitor,
        metrics_logger: MetricsLogger,
        update_manager: UpdateManager,
        esp_flash_manager: EspFlashManager,
        history_db: HistoryDB,
        worker_pool: WorkerPool,
        processing_loop: ProcessingLoop,
        ws_broadcast: WsBroadcastService,
    ) -> None:
        self._config = config
        self._registry = registry
        self._processor = processor
        self._control_plane = control_plane
        self._ws_hub = ws_hub
        self._gps_monitor = gps_monitor
        self._metrics_logger = metrics_logger
        self._update_manager = update_manager
        self._esp_flash_manager = esp_flash_manager
        self._history_db = history_db
        self._worker_pool = worker_pool
        self._processing_loop = processing_loop
        self._ws_broadcast = ws_broadcast
        self.tasks: list[asyncio.Task] = []
        self._data_transport: asyncio.DatagramTransport | None = None
        self._data_consumer_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Launch UDP receiver, control plane, and background async tasks."""
        self._data_transport, self._data_consumer_task = await start_udp_data_receiver(
            host=self._config.udp.data_host,
            port=self._config.udp.data_port,
            registry=self._registry,
            processor=self._processor,
            queue_maxsize=self._config.udp.data_queue_maxsize,
        )
        await self._control_plane.start()
        self.tasks = [
            asyncio.create_task(self._processing_loop.run(), name="processing-loop"),
            asyncio.create_task(
                self._ws_hub.run(
                    self._config.processing.ui_push_hz,
                    self._ws_broadcast.build_payload,
                    on_tick=self._ws_broadcast.on_tick,
                ),
                name="ws-broadcast",
            ),
            asyncio.create_task(self._metrics_logger.run(), name="metrics-log"),
            asyncio.create_task(
                self._gps_monitor.run(
                    host=self._config.gps.gpsd_host,
                    port=self._config.gps.gpsd_port,
                ),
                name="gps-speed",
            ),
        ]
        # Recover interrupted update jobs (best-effort, must not crash server)
        self.tasks.append(
            asyncio.create_task(
                self._update_manager.startup_recover(),
                name="update-startup-recover",
            )
        )

    async def stop(self) -> None:
        """Graceful shutdown: cancel tasks, close DB/transport, wait for post-analysis."""
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
        managed = [
            self._update_manager.job_task,
            self._esp_flash_manager.job_task,
        ]
        for task in managed:
            if task is not None:
                task.cancel()
        for task in managed:
            if task is not None and not task.done():
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(asyncio.shield(task), timeout=10.0)

        self._metrics_logger.stop_logging()
        analysis_timeout_s = self._config.logging.shutdown_analysis_timeout_s
        finished = await asyncio.to_thread(
            self._metrics_logger.wait_for_post_analysis, analysis_timeout_s
        )
        if not finished:
            LOGGER.warning(
                "Post-analysis did not finish within %.1fs on shutdown; "
                "results for the last run may be lost.",
                analysis_timeout_s,
            )

        try:
            self._control_plane.close()
        except Exception:
            LOGGER.warning("Error closing control plane", exc_info=True)
        try:
            if self._data_transport is not None:
                self._data_transport.close()
                self._data_transport = None
        except Exception:
            LOGGER.warning("Error closing data transport", exc_info=True)
        if self._data_consumer_task is not None:
            self._data_consumer_task.cancel()
            await asyncio.gather(self._data_consumer_task, return_exceptions=True)
            self._data_consumer_task = None
        try:
            await asyncio.to_thread(self._worker_pool.shutdown, True)
        except Exception:
            LOGGER.warning("Error shutting down worker pool", exc_info=True)
        try:
            self._history_db.close()
        except Exception:
            LOGGER.warning("Error closing history DB", exc_info=True)
        LOGGER.info("RuntimeState stopped cleanly.")
