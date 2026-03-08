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
    from .subsystems import (
        RuntimeDiagnosticsSubsystem,
        RuntimeIngressSubsystem,
        RuntimePersistenceSubsystem,
        RuntimeProcessingSubsystem,
        RuntimeSettingsSubsystem,
        RuntimeUpdateSubsystem,
        RuntimeWebsocketSubsystem,
    )

LOGGER = logging.getLogger(__name__)


class LifecycleManager:
    """Manages server startup (UDP receiver, background tasks) and graceful shutdown."""

    __slots__ = (
        "_config",
        "_ingress",
        "_settings",
        "_diagnostics",
        "_persistence",
        "_updates",
        "_processing",
        "_websocket",
        "tasks",
        "_data_transport",
        "_data_consumer_task",
    )

    def __init__(
        self,
        *,
        config: AppConfig,
        ingress: RuntimeIngressSubsystem,
        settings: RuntimeSettingsSubsystem,
        diagnostics: RuntimeDiagnosticsSubsystem,
        persistence: RuntimePersistenceSubsystem,
        updates: RuntimeUpdateSubsystem,
        processing: RuntimeProcessingSubsystem,
        websocket: RuntimeWebsocketSubsystem,
    ) -> None:
        self._config = config
        self._ingress = ingress
        self._settings = settings
        self._diagnostics = diagnostics
        self._persistence = persistence
        self._updates = updates
        self._processing = processing
        self._websocket = websocket
        self.tasks: list[asyncio.Task] = []
        self._data_transport: asyncio.DatagramTransport | None = None
        self._data_consumer_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Launch UDP receiver, control plane, and background async tasks."""
        self._data_transport, self._data_consumer_task = await start_udp_data_receiver(
            host=self._config.udp.data_host,
            port=self._config.udp.data_port,
            registry=self._ingress.registry,
            processor=self._ingress.processor,
            queue_maxsize=self._config.udp.data_queue_maxsize,
        )
        await self._ingress.control_plane.start()
        self.tasks = [
            asyncio.create_task(self._processing.loop.run(), name="processing-loop"),
            asyncio.create_task(
                self._websocket.hub.run(
                    self._config.processing.ui_push_hz,
                    self._websocket.broadcast.build_payload,
                    on_tick=self._websocket.broadcast.on_tick,
                ),
                name="ws-broadcast",
            ),
            asyncio.create_task(self._diagnostics.metrics_logger.run(), name="metrics-log"),
            asyncio.create_task(
                self._settings.gps_monitor.run(
                    host=self._config.gps.gpsd_host,
                    port=self._config.gps.gpsd_port,
                ),
                name="gps-speed",
            ),
        ]
        # Recover interrupted update jobs (best-effort, must not crash server)
        self.tasks.append(
            asyncio.create_task(
                self._updates.update_manager.startup_recover(),
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
            self._updates.update_manager.job_task,
            self._updates.esp_flash_manager.job_task,
        ]
        for task in managed:
            if task is not None:
                task.cancel()
        for task in managed:
            if task is not None and not task.done():
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(asyncio.shield(task), timeout=10.0)

        analysis_timeout_s = self._config.logging.shutdown_analysis_timeout_s
        finished = await asyncio.to_thread(
            self._diagnostics.metrics_logger.shutdown,
            analysis_timeout_s,
        )
        if not finished:
            LOGGER.warning(
                "Post-analysis did not finish within %.1fs on shutdown; "
                "results for the last run may be lost.",
                analysis_timeout_s,
            )

        try:
            self._ingress.control_plane.close()
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
            await asyncio.to_thread(self._ingress.worker_pool.shutdown, True)
        except Exception:
            LOGGER.warning("Error shutting down worker pool", exc_info=True)
        try:
            self._persistence.history_db.close()
        except Exception:
            LOGGER.warning("Error closing history DB", exc_info=True)
        LOGGER.info("Runtime lifecycle stopped cleanly.")
