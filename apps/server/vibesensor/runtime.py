"""RuntimeState – thin orchestration layer: lifecycle, processing loop, WS broadcast.

Extracted from ``app.py`` so that the orchestration logic is independently
testable and ``app.py`` stays a thin FastAPI wiring layer.

Internal helpers
----------------
- ``ProcessingLoopState`` – mutable failure-tracking state for the processing loop.
- ``WsBroadcastCache`` – tick counter and per-tick caches for WS payload assembly.
- ``_apply_car_settings`` / ``_apply_speed_source_settings`` – stateless settings applicators.
- ``_rotational_basis_speed_source`` / ``_build_rotational_speeds_payload`` – stateless payload
  builders.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any

from .analysis_settings import AnalysisSettingsStore
from .config import AppConfig
from .constants import (
    SECONDS_PER_MINUTE,
)
from .diagnostics_shared import (
    build_order_bands,
    vehicle_orders_hz,
)
from .esp_flash_manager import EspFlashManager
from .gps_speed import GPSSpeedMonitor
from .history_db import HistoryDB
from .live_diagnostics.engine import LiveDiagnosticsEngine
from .metrics_log import MetricsLogger
from .processing import SignalProcessor
from .registry import ClientRegistry
from .runlog import utc_now_iso
from .settings_store import SettingsStore
from .udp_control_tx import UDPControlPlane
from .udp_data_rx import start_udp_data_receiver
from .update_manager import UpdateManager
from .worker_pool import WorkerPool
from .ws_hub import WebSocketHub
from .ws_models import SCHEMA_VERSION

LOGGER = logging.getLogger(__name__)

# Processing-loop resilience constants
MAX_CONSECUTIVE_FAILURES = 25
"""After this many consecutive processing failures, enter fatal backoff."""

FAILURE_BACKOFF_S = 30
"""Seconds to sleep on fatal failure threshold before resetting."""

STALE_DATA_AGE_S = 2.0
"""Clients without fresh UDP data within this window are excluded from spectrum output."""


# ---------------------------------------------------------------------------
# ProcessingLoopState – failure tracking and mismatch logging
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ProcessingLoopState:
    """Mutable tracking state for the processing loop.

    Extracted from ``RuntimeState`` so the loop's counters and mismatch
    log-guards form a coherent, narrowly-scoped unit.
    """

    processing_state: str = "ok"
    processing_failure_count: int = 0
    sample_rate_mismatch_logged: set[str] = field(default_factory=set)
    frame_size_mismatch_logged: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# WsBroadcastCache – tick counter and per-tick result caches
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class WsBroadcastCache:
    """Tick counter and per-tick caches for WebSocket payload assembly.

    Extracted from ``RuntimeState`` so that cache-staleness logic and the
    tick/heavy-tick toggle form a single coherent unit rather than scattered
    fields on the god object.
    """

    tick: int = 0
    include_heavy: bool = True
    analysis_metadata: dict[str, object] | None = None
    analysis_samples: list[dict[str, object]] = field(default_factory=list)
    analysis_tick: int = -1
    diagnostics: dict[str, object] | None = None
    diagnostics_tick: int = -1
    diagnostics_heavy: bool = True

    def advance(self, heavy_every: int) -> None:
        """Advance the tick counter and update ``include_heavy``."""
        self.tick += 1
        self.include_heavy = (self.tick % heavy_every) == 0

    def refresh_analysis(
        self,
        metrics_logger: MetricsLogger,
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        """Return (metadata, samples), refreshing only when the cache is stale.

        On heavy ticks the cache is always refreshed.  On light ticks the
        existing cache is reused if it was populated at least once.
        """
        need_refresh = self.analysis_metadata is None or (
            self.include_heavy and self.analysis_tick != self.tick
        )
        if need_refresh:
            metadata, samples = metrics_logger.analysis_snapshot()
            self.analysis_metadata = metadata
            self.analysis_samples = samples
            self.analysis_tick = self.tick
        assert self.analysis_metadata is not None, (
            "analysis cache must be populated: need_refresh was True or cache was valid"
        )
        return self.analysis_metadata, self.analysis_samples

    def refresh_diagnostics(
        self,
        live_diagnostics: LiveDiagnosticsEngine,
        *,
        speed_mps: float | None,
        clients: list[dict[str, Any]],
        spectra: dict[str, Any] | None,
        settings: dict[str, Any],
        analysis_metadata: dict[str, object],
        analysis_samples: list[dict[str, object]],
        language: str,
    ) -> dict[str, object]:
        """Return diagnostics payload, refreshing only when the cache is stale."""
        cache_valid = (
            self.diagnostics is not None
            and self.diagnostics_tick == self.tick
            and self.diagnostics_heavy == self.include_heavy
        )
        if cache_valid:
            assert self.diagnostics is not None, (
                "diagnostics cache must be populated when cache_valid is True"
            )
            return self.diagnostics
        diagnostics = live_diagnostics.update(
            speed_mps=speed_mps,
            clients=clients,
            spectra=spectra,
            settings=settings,
            finding_metadata=analysis_metadata,
            finding_samples=analysis_samples,
            language=language,
        )
        self.diagnostics = diagnostics
        self.diagnostics_tick = self.tick
        self.diagnostics_heavy = self.include_heavy
        return diagnostics


# ---------------------------------------------------------------------------
# Settings applicators (stateless module-level helpers)
# ---------------------------------------------------------------------------


def _apply_car_settings(
    settings_store: SettingsStore,
    analysis_settings: AnalysisSettingsStore,
) -> None:
    """Push active car aspects into the shared AnalysisSettingsStore."""
    aspects = settings_store.active_car_aspects()
    if aspects:
        analysis_settings.update(aspects)


def _apply_speed_source_settings(
    settings_store: SettingsStore,
    gps_monitor: GPSSpeedMonitor,
) -> None:
    """Push speed-source settings into GPSSpeedMonitor."""
    ss = settings_store.get_speed_source()
    gps_monitor.set_manual_source_selected(ss["speedSource"] == "manual")
    if ss["manualSpeedKph"] is not None:
        gps_monitor.set_speed_override_kmh(ss["manualSpeedKph"])
    else:
        gps_monitor.set_speed_override_kmh(None)
    gps_monitor.set_fallback_settings(
        stale_timeout_s=ss.get("staleTimeoutS"),
        fallback_mode=ss.get("fallbackMode"),
    )


# ---------------------------------------------------------------------------
# Rotational-speed payload helpers (stateless module-level helpers)
# ---------------------------------------------------------------------------


def _rotational_basis_speed_source(
    settings_store: SettingsStore,
    gps_monitor: GPSSpeedMonitor,
    *,
    resolution_source: str | None = None,
) -> str:
    """Determine the basis speed source label for rotational RPM display."""
    speed_source = settings_store.get_speed_source()
    selected_source = str(speed_source.get("speedSource") or "gps").lower()
    if selected_source == "manual":
        return "manual"
    if selected_source == "obd2":
        return "obd2"
    # Use the pre-resolved source when available for snapshot consistency.
    if resolution_source is not None:
        if resolution_source == "fallback_manual":
            return "fallback_manual"
        if gps_monitor.gps_enabled:
            return "gps"
    else:
        # Fallback for callers that don't pass a resolution.
        if gps_monitor.fallback_active:
            return "fallback_manual"
        if gps_monitor.gps_enabled:
            return "gps"
    return "unknown"


def _build_rotational_speeds_payload(
    *,
    basis_speed_source: str,
    speed_mps: float | None,
    analysis_settings: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the ``rotational_speeds`` sub-dict for the WS payload."""
    # Determine failure reason early to avoid closure allocation and
    # full-dict construction on the common no-speed / invalid-settings paths.
    if speed_mps is None or speed_mps <= 0:
        reason: str | None = "speed_unavailable"
        orders_hz = None
    else:
        orders_hz = vehicle_orders_hz(speed_mps=speed_mps, settings=analysis_settings)
        reason = "invalid_vehicle_settings" if orders_hz is None else None

    if reason is not None:
        _component: dict[str, Any] = {"rpm": None, "mode": "calculated", "reason": reason}
        return {
            "basis_speed_source": basis_speed_source,
            "wheel": {**_component},
            "driveshaft": {**_component},
            "engine": {**_component},
            "order_bands": None,
        }

    wheel_rpm = float(orders_hz["wheel_hz"]) * SECONDS_PER_MINUTE
    drive_rpm = float(orders_hz["drive_hz"]) * SECONDS_PER_MINUTE
    engine_rpm = float(orders_hz["engine_hz"]) * SECONDS_PER_MINUTE

    return {
        "basis_speed_source": basis_speed_source,
        "wheel": {"rpm": wheel_rpm, "mode": "calculated", "reason": None},
        "driveshaft": {"rpm": drive_rpm, "mode": "calculated", "reason": None},
        "engine": {"rpm": engine_rpm, "mode": "calculated", "reason": None},
        "order_bands": build_order_bands(orders_hz, analysis_settings),
    }


# ---------------------------------------------------------------------------
# RuntimeState – thin orchestration layer
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RuntimeState:
    """Thin orchestration layer: holds service refs and coordinates lifecycle.

    Mutable state has been extracted into focused sub-objects:

    - ``loop_state``: processing-loop failure tracking and mismatch log-guards.
    - ``ws_cache``: WebSocket tick counter and per-tick payload caches.

    The public surface (``processing_state``, ``processing_failure_count``,
    ``ws_tick``, ``ws_include_heavy``) is preserved as properties for
    backward compatibility with callers that read/write these directly.
    """

    config: AppConfig
    registry: ClientRegistry
    processor: SignalProcessor
    control_plane: UDPControlPlane
    ws_hub: WebSocketHub
    gps_monitor: GPSSpeedMonitor
    analysis_settings: AnalysisSettingsStore
    metrics_logger: MetricsLogger
    live_diagnostics: LiveDiagnosticsEngine
    settings_store: SettingsStore
    history_db: HistoryDB
    update_manager: UpdateManager
    esp_flash_manager: EspFlashManager
    worker_pool: WorkerPool
    tasks: list[asyncio.Task] = field(default_factory=list)
    data_transport: asyncio.DatagramTransport | None = None
    data_consumer_task: asyncio.Task | None = None
    loop_state: ProcessingLoopState = field(default_factory=ProcessingLoopState)
    ws_cache: WsBroadcastCache = field(default_factory=WsBroadcastCache)

    # -- Backward-compatible property delegates ----------------------------
    # Allow external code (health route, tests) to read/write the narrowly-
    # extracted state fields through the original flat attribute names.

    @property
    def processing_state(self) -> str:
        return self.loop_state.processing_state

    @processing_state.setter
    def processing_state(self, value: str) -> None:
        self.loop_state.processing_state = value

    @property
    def processing_failure_count(self) -> int:
        return self.loop_state.processing_failure_count

    @processing_failure_count.setter
    def processing_failure_count(self, value: int) -> None:
        self.loop_state.processing_failure_count = value

    @property
    def ws_tick(self) -> int:
        return self.ws_cache.tick

    @ws_tick.setter
    def ws_tick(self, value: int) -> None:
        self.ws_cache.tick = value

    @property
    def ws_include_heavy(self) -> bool:
        return self.ws_cache.include_heavy

    @ws_include_heavy.setter
    def ws_include_heavy(self, value: bool) -> None:
        self.ws_cache.include_heavy = value

    # -- settings helpers ---------------------------------------------------

    def apply_car_settings(self) -> None:
        """Push active car aspects into the shared AnalysisSettingsStore."""
        _apply_car_settings(self.settings_store, self.analysis_settings)

    def apply_speed_source_settings(self) -> None:
        """Push speed-source settings into GPSSpeedMonitor."""
        _apply_speed_source_settings(self.settings_store, self.gps_monitor)

    # -- WS broadcast helpers -----------------------------------------------

    def on_ws_broadcast_tick(self) -> None:
        heavy_every = max(
            1,
            int(
                self.config.processing.ui_push_hz / max(1, self.config.processing.ui_heavy_push_hz)
            ),
        )
        self.ws_cache.advance(heavy_every)

    def build_ws_payload(self, selected_client: str | None) -> dict[str, Any]:
        clients = self.registry.snapshot_for_api()
        active = selected_client
        if active is None and clients:
            active = clients[0]["id"]
        client_ids = [c["id"] for c in clients]
        # Only include spectrum data for clients with recent UDP data
        # to prevent stale buffer data from driving diagnostics/events.
        fresh_ids = self.processor.clients_with_recent_data(client_ids, max_age_s=STALE_DATA_AGE_S)

        resolution = self.gps_monitor.resolve_speed()
        speed_mps = resolution.speed_mps
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "server_time": utc_now_iso(),
            "speed_mps": speed_mps,
            "clients": clients,
            "selected_client_id": active,
        }
        analysis_settings_snapshot = self.analysis_settings.snapshot()
        basis = _rotational_basis_speed_source(
            self.settings_store,
            self.gps_monitor,
            resolution_source=resolution.source,
        )
        payload["rotational_speeds"] = _build_rotational_speeds_payload(
            basis_speed_source=basis,
            speed_mps=speed_mps,
            analysis_settings=analysis_settings_snapshot,
        )
        analysis_metadata, analysis_samples = self.ws_cache.refresh_analysis(self.metrics_logger)
        if self.ws_cache.include_heavy:
            payload["spectra"] = self.processor.multi_spectrum_payload(fresh_ids)
        payload["diagnostics"] = self.ws_cache.refresh_diagnostics(
            self.live_diagnostics,
            speed_mps=speed_mps,
            clients=clients,
            spectra=payload.get("spectra") if self.ws_cache.include_heavy else None,
            settings=analysis_settings_snapshot,
            analysis_metadata=analysis_metadata,
            analysis_samples=analysis_samples,
            language=self.settings_store.language,
        )
        return payload

    # -- lifecycle ----------------------------------------------------------

    async def processing_loop(self) -> None:
        """~100 ms tick loop: evict stale clients, compute metrics, handle failures."""
        interval = 1.0 / max(1, self.config.processing.fft_update_hz)
        consecutive_failures = 0
        _sync_clock_tick = 0
        _SYNC_CLOCK_EVERY_N_TICKS = max(1, int(5.0 / interval))  # ~every 5 s
        while True:
            try:
                _sync_clock_tick += 1
                if _sync_clock_tick >= _SYNC_CLOCK_EVERY_N_TICKS:
                    _sync_clock_tick = 0
                    if self.control_plane is not None:
                        self.control_plane.broadcast_sync_clock()
                self.registry.evict_stale()
                active_ids = self.registry.active_client_ids()
                # Only recompute metrics for clients that received new data
                # since the last tick.  This prevents stale ring-buffer data
                # from cycling through the pipeline indefinitely.
                fresh_ids = self.processor.clients_with_recent_data(
                    active_ids, max_age_s=STALE_DATA_AGE_S
                )
                sample_rates: dict[str, int] = {}
                loop_state = self.loop_state  # local alias avoids repeated attr lookup in the loop
                for client_id in fresh_ids:
                    record = self.registry.get(client_id)
                    if record is None:
                        continue
                    sample_rates[client_id] = record.sample_rate_hz
                    client_rate = int(record.sample_rate_hz or 0)
                    default_rate = self.config.processing.sample_rate_hz
                    if (
                        client_rate > 0
                        and client_rate != default_rate
                        and client_id not in loop_state.sample_rate_mismatch_logged
                    ):
                        loop_state.sample_rate_mismatch_logged.add(client_id)
                        LOGGER.warning(
                            "Client %s uses sample_rate_hz=%d; default config is %d.",
                            client_id,
                            client_rate,
                            default_rate,
                        )
                    frame_samples = int(record.frame_samples or 0)
                    if (
                        frame_samples > 0
                        and frame_samples > self.config.processing.fft_n
                        and client_id not in loop_state.frame_size_mismatch_logged
                    ):
                        loop_state.frame_size_mismatch_logged.add(client_id)
                        LOGGER.error(
                            "Client %s reported frame_samples=%d larger than fft_n=%d; "
                            "ingest may be degraded.",
                            client_id,
                            frame_samples,
                            self.config.processing.fft_n,
                        )
                metrics_by_client = await asyncio.to_thread(
                    self.processor.compute_all,
                    fresh_ids,
                    sample_rates_hz=sample_rates,
                )
                for client_id, metrics in metrics_by_client.items():
                    self.registry.set_latest_metrics(client_id, metrics)
                self.processor.evict_clients(set(active_ids))
                consecutive_failures = 0
                loop_state.processing_state = "ok"
            except Exception:
                consecutive_failures += 1
                self.loop_state.processing_failure_count += 1
                is_fatal = consecutive_failures >= MAX_CONSECUTIVE_FAILURES
                self.loop_state.processing_state = "fatal" if is_fatal else "degraded"
                LOGGER.warning("Processing loop tick failed; will retry.", exc_info=True)
                if is_fatal:
                    LOGGER.error(
                        "Processing loop hit %d failures; backing off %d s then resetting",
                        MAX_CONSECUTIVE_FAILURES,
                        FAILURE_BACKOFF_S,
                    )
                    await asyncio.sleep(FAILURE_BACKOFF_S)
                    consecutive_failures = 0
                    self.loop_state.processing_state = "degraded"
                    LOGGER.info(
                        "Processing loop resuming after fatal-backoff; "
                        "total failure count so far: %d",
                        self.loop_state.processing_failure_count,
                    )
            delay = (
                interval
                if consecutive_failures == 0
                else min(5.0, interval * (2 ** min(6, consecutive_failures)))
            )
            await asyncio.sleep(delay)

    async def start(self) -> None:
        """Launch UDP receiver, control plane, and background async tasks."""
        self.data_transport, self.data_consumer_task = await start_udp_data_receiver(
            host=self.config.udp.data_host,
            port=self.config.udp.data_port,
            registry=self.registry,
            processor=self.processor,
            queue_maxsize=self.config.udp.data_queue_maxsize,
        )
        await self.control_plane.start()
        self.tasks = [
            asyncio.create_task(self.processing_loop(), name="processing-loop"),
            asyncio.create_task(
                self.ws_hub.run(
                    self.config.processing.ui_push_hz,
                    self.build_ws_payload,
                    on_tick=self.on_ws_broadcast_tick,
                ),
                name="ws-broadcast",
            ),
            asyncio.create_task(self.metrics_logger.run(), name="metrics-log"),
            asyncio.create_task(
                self.gps_monitor.run(
                    host=self.config.gps.gpsd_host,
                    port=self.config.gps.gpsd_port,
                ),
                name="gps-speed",
            ),
        ]
        # Recover interrupted update jobs (best-effort, must not crash server)
        self.tasks.append(
            asyncio.create_task(
                self.update_manager.startup_recover(),
                name="update-startup-recover",
            )
        )

    async def stop(self) -> None:
        """Graceful shutdown: cancel tasks, close DB/transport, wait for post-analysis."""
        for task in self.tasks:
            task.cancel()
        # Wait up to 15 s for tasks to respond to cancellation.  Tasks stuck in
        # asyncio.to_thread (e.g. blocking FFT) could otherwise hang shutdown
        # indefinitely if we used a bare asyncio.gather with no timeout.
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
            self.update_manager.job_task,
            self.esp_flash_manager.job_task,
        ]
        for task in managed:
            if task is not None:
                task.cancel()
        for task in managed:
            if task is not None and not task.done():
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(asyncio.shield(task), timeout=10.0)

        self.metrics_logger.stop_logging()
        analysis_timeout_s = self.config.logging.shutdown_analysis_timeout_s
        finished = await asyncio.to_thread(
            self.metrics_logger.wait_for_post_analysis, analysis_timeout_s
        )
        if not finished:
            LOGGER.warning(
                "Post-analysis did not finish within %.1fs on shutdown; "
                "results for the last run may be lost.",
                analysis_timeout_s,
            )

        try:
            self.control_plane.close()
        except Exception:
            LOGGER.warning("Error closing control plane", exc_info=True)
        try:
            if self.data_transport is not None:
                self.data_transport.close()
                self.data_transport = None
        except Exception:
            LOGGER.warning("Error closing data transport", exc_info=True)
        if self.data_consumer_task is not None:
            self.data_consumer_task.cancel()
            await asyncio.gather(self.data_consumer_task, return_exceptions=True)
            self.data_consumer_task = None
        try:
            # Run the blocking executor shutdown off the event loop so we do
            # not stall other coroutines (e.g. lifespan finalisation) while
            # waiting for in-flight FFT threads to drain.
            await asyncio.to_thread(self.worker_pool.shutdown, True)
        except Exception:
            LOGGER.warning("Error shutting down worker pool", exc_info=True)
        try:
            self.history_db.close()
        except Exception:
            LOGGER.warning("Error closing history DB", exc_info=True)
        LOGGER.info("RuntimeState stopped cleanly.")
