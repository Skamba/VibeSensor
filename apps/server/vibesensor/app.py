"""Runtime orchestration for ingestion -> processing -> diagnostics -> WS/API.

Boundary note for maintainers:
- Keep this module focused on orchestration, not algorithm details.
- Metric math belongs in `processing.py` / `analysis/*`.
- API schemas belong in `api.py`.
"""

from __future__ import annotations

import argparse
import asyncio
import errno
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from vibesensor_core.sensor_units import get_accel_scale_g_per_lsb

from .analysis_settings import AnalysisSettingsStore
from .api import create_router
from .config import SERVER_DIR, AppConfig, load_config
from .constants import (
    FREQUENCY_EPSILON_HZ,
    HARMONIC_2X,
    MIN_OVERLAP_TOLERANCE,
    SECONDS_PER_MINUTE,
)
from .diagnostics_shared import (
    build_diagnostic_settings,
    order_tolerances,
    vehicle_orders_hz,
)
from .esp_flash_manager import EspFlashManager
from .gps_speed import GPSSpeedMonitor
from .history_db import HistoryDB
from .live_diagnostics import LiveDiagnosticsEngine
from .metrics_log import MetricsLogger
from .processing import SignalProcessor
from .registry import ClientRegistry
from .settings_store import SettingsStore
from .udp_control_tx import UDPControlPlane
from .udp_data_rx import start_udp_data_receiver
from .update_manager import UpdateManager
from .worker_pool import WorkerPool
from .ws_hub import WebSocketHub

LOGGER = logging.getLogger(__name__)
BACKUP_SERVER_PORT = 8000

# Processing-loop resilience constants
MAX_CONSECUTIVE_FAILURES = 25
"""After this many consecutive processing failures, enter fatal backoff."""

FAILURE_BACKOFF_S = 30
"""Seconds to sleep on fatal failure threshold before resetting."""

STALE_DATA_AGE_S = 2.0
"""Clients without fresh UDP data within this window are excluded from spectrum output."""


def _build_order_bands(
    orders_hz: dict[str, Any],
    analysis_settings: dict[str, Any],
) -> list[dict[str, Any]]:
    """Pre-compute order tolerance bands so the frontend doesn't duplicate this math."""
    resolved = build_diagnostic_settings(analysis_settings)
    wheel_hz = float(orders_hz["wheel_hz"])
    drive_hz = float(orders_hz["drive_hz"])
    engine_hz = float(orders_hz["engine_hz"])
    wheel_tol, drive_tol, engine_tol = order_tolerances(orders_hz, resolved)
    bands: list[dict[str, Any]] = [
        {"key": "wheel_1x", "center_hz": wheel_hz, "tolerance": wheel_tol},
        {"key": "wheel_2x", "center_hz": wheel_hz * HARMONIC_2X, "tolerance": wheel_tol},
    ]
    overlap_tol = max(
        MIN_OVERLAP_TOLERANCE,
        orders_hz["drive_uncertainty_pct"] + orders_hz["engine_uncertainty_pct"],
    )
    if abs(drive_hz - engine_hz) / max(FREQUENCY_EPSILON_HZ, engine_hz) < overlap_tol:
        bands.append(
            {
                "key": "driveshaft_engine_1x",
                "center_hz": drive_hz,
                "tolerance": max(drive_tol, engine_tol),
            }
        )
    else:
        bands.append({"key": "driveshaft_1x", "center_hz": drive_hz, "tolerance": drive_tol})
        bands.append({"key": "engine_1x", "center_hz": engine_hz, "tolerance": engine_tol})
    bands.append(
        {"key": "engine_2x", "center_hz": engine_hz * HARMONIC_2X, "tolerance": engine_tol}
    )
    return bands


@dataclass(slots=True)
class RuntimeState:
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
    tasks: list[asyncio.Task] = field(default_factory=list)
    data_transport: asyncio.DatagramTransport | None = None
    data_consumer_task: asyncio.Task | None = None
    sample_rate_mismatch_logged: set[str] = field(default_factory=set)
    frame_size_mismatch_logged: set[str] = field(default_factory=set)
    processing_state: str = "ok"
    processing_failure_count: int = 0
    ws_tick: int = 0
    ws_include_heavy: bool = True
    cached_analysis_metadata: dict[str, object] | None = None
    cached_analysis_samples: list[dict[str, object]] = field(default_factory=list)
    cached_analysis_tick: int = -1
    cached_diagnostics: dict[str, object] | None = None
    cached_diagnostics_tick: int = -1
    cached_diagnostics_heavy: bool = True

    def apply_car_settings(self) -> None:
        """Push active car aspects into the shared AnalysisSettingsStore."""
        aspects = self.settings_store.active_car_aspects()
        if aspects:
            self.analysis_settings.update(aspects)

    def apply_speed_source_settings(self) -> None:
        """Push speed-source settings into GPSSpeedMonitor."""
        ss = self.settings_store.get_speed_source()
        self.gps_monitor.set_manual_source_selected(ss["speedSource"] == "manual")
        if ss["manualSpeedKph"] is not None:
            self.gps_monitor.set_speed_override_kmh(ss["manualSpeedKph"])
        else:
            self.gps_monitor.set_speed_override_kmh(None)
        self.gps_monitor.set_fallback_settings(
            stale_timeout_s=ss.get("staleTimeoutS"),
            fallback_mode=ss.get("fallbackMode"),
        )

    def _rotational_basis_speed_source(
        self,
        *,
        resolution_source: str | None = None,
    ) -> str:
        speed_source = self.settings_store.get_speed_source()
        selected_source = str(speed_source.get("speedSource") or "gps").lower()
        if selected_source == "manual":
            return "manual"
        if selected_source == "obd2":
            return "obd2"
        # Use the pre-resolved source when available for snapshot consistency.
        if resolution_source is not None:
            if resolution_source == "fallback_manual":
                return "fallback_manual"
            if self.gps_monitor.gps_enabled:
                return "gps"
        else:
            # Fallback for callers that don't pass a resolution.
            if self.gps_monitor.fallback_active:
                return "fallback_manual"
            if self.gps_monitor.gps_enabled:
                return "gps"
        return "unknown"

    def _build_rotational_speeds_payload(
        self,
        *,
        speed_mps: float | None,
        analysis_settings: dict[str, Any],
        resolution_source: str | None = None,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "basis_speed_source": self._rotational_basis_speed_source(
                resolution_source=resolution_source,
            ),
            "wheel": {"rpm": None, "mode": "calculated", "reason": None},
            "driveshaft": {"rpm": None, "mode": "calculated", "reason": None},
            "engine": {"rpm": None, "mode": "calculated", "reason": None},
            "order_bands": None,
        }

        def _set_all_reasons(reason: str) -> dict[str, Any]:
            for component in ("wheel", "driveshaft", "engine"):
                out[component]["reason"] = reason
            return out

        if speed_mps is None or speed_mps <= 0:
            return _set_all_reasons("speed_unavailable")

        orders_hz = vehicle_orders_hz(speed_mps=speed_mps, settings=analysis_settings)
        if orders_hz is None:
            return _set_all_reasons("invalid_vehicle_settings")

        out["wheel"]["rpm"] = float(orders_hz["wheel_hz"]) * SECONDS_PER_MINUTE
        out["driveshaft"]["rpm"] = float(orders_hz["drive_hz"]) * SECONDS_PER_MINUTE
        out["engine"]["rpm"] = float(orders_hz["engine_hz"]) * SECONDS_PER_MINUTE

        out["order_bands"] = _build_order_bands(orders_hz, analysis_settings)
        return out

    def on_ws_broadcast_tick(self) -> None:
        self.ws_tick += 1
        heavy_every = max(
            1,
            int(
                self.config.processing.ui_push_hz / max(1, self.config.processing.ui_heavy_push_hz)
            ),
        )
        self.ws_include_heavy = (self.ws_tick % heavy_every) == 0

    def _refresh_analysis_cache(self) -> tuple[dict[str, object], list[dict[str, object]]]:
        """Return (metadata, samples), refreshing only when the cache is stale.

        On heavy ticks the cache is always refreshed.  On light ticks the
        existing cache is reused if it was populated at least once.
        """
        need_refresh = (
            self.ws_include_heavy
            and (self.cached_analysis_tick != self.ws_tick or self.cached_analysis_metadata is None)
        ) or self.cached_analysis_metadata is None
        if need_refresh:
            metadata, samples = self.metrics_logger.analysis_snapshot()
            self.cached_analysis_metadata = metadata
            self.cached_analysis_samples = samples
            self.cached_analysis_tick = self.ws_tick
        return self.cached_analysis_metadata, self.cached_analysis_samples  # type: ignore[return-value]

    def _refresh_diagnostics_cache(
        self,
        *,
        speed_mps: float | None,
        clients: list[dict[str, Any]],
        spectra: dict[str, Any] | None,
        settings: dict[str, Any],
        analysis_metadata: dict[str, object],
        analysis_samples: list[dict[str, object]],
    ) -> dict[str, object]:
        """Return diagnostics payload, refreshing only when the cache is stale."""
        cache_valid = (
            self.cached_diagnostics is not None
            and self.cached_diagnostics_tick == self.ws_tick
            and self.cached_diagnostics_heavy == self.ws_include_heavy
        )
        if cache_valid:
            return self.cached_diagnostics  # type: ignore[return-value]
        diagnostics = self.live_diagnostics.update(
            speed_mps=speed_mps,
            clients=clients,
            spectra=spectra,
            settings=settings,
            finding_metadata=analysis_metadata,
            finding_samples=analysis_samples,
            language=self.settings_store.language,
        )
        self.cached_diagnostics = diagnostics
        self.cached_diagnostics_tick = self.ws_tick
        self.cached_diagnostics_heavy = self.ws_include_heavy
        return diagnostics

    def build_ws_payload(self, selected_client: str | None) -> dict[str, Any]:
        from .ws_models import SCHEMA_VERSION

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
            "server_time": datetime.now(UTC).isoformat(),
            "speed_mps": speed_mps,
            "clients": clients,
            "selected_client_id": active,
        }
        analysis_settings_snapshot = self.analysis_settings.snapshot()
        payload["rotational_speeds"] = self._build_rotational_speeds_payload(
            speed_mps=speed_mps,
            analysis_settings=analysis_settings_snapshot,
            resolution_source=resolution.source,
        )
        analysis_metadata, analysis_samples = self._refresh_analysis_cache()
        if self.ws_include_heavy:
            payload["spectra"] = self.processor.multi_spectrum_payload(fresh_ids)
        payload["diagnostics"] = self._refresh_diagnostics_cache(
            speed_mps=speed_mps,
            clients=clients,
            spectra=payload.get("spectra") if self.ws_include_heavy else None,
            settings=analysis_settings_snapshot,
            analysis_metadata=analysis_metadata,
            analysis_samples=analysis_samples,
        )
        return payload


def create_app(config_path: Path | None = None) -> FastAPI:
    config = load_config(config_path)

    history_db = HistoryDB(config.logging.history_db_path)
    recovered_runs = history_db.recover_stale_recording_runs()
    if recovered_runs:
        LOGGER.warning("Recovered %d stale recording run(s) on startup", recovered_runs)

    registry = ClientRegistry(
        db=history_db,
        stale_ttl_seconds=config.processing.client_ttl_seconds,
    )
    accel_scale_g_per_lsb = (
        config.processing.accel_scale_g_per_lsb
        if config.processing.accel_scale_g_per_lsb is not None
        else get_accel_scale_g_per_lsb(config.logging.sensor_model)
    )
    worker_pool = WorkerPool(max_workers=4, thread_name_prefix="vibesensor-fft")
    processor = SignalProcessor(
        sample_rate_hz=config.processing.sample_rate_hz,
        waveform_seconds=config.processing.waveform_seconds,
        waveform_display_hz=config.processing.waveform_display_hz,
        fft_n=config.processing.fft_n,
        spectrum_min_hz=config.processing.spectrum_min_hz,
        spectrum_max_hz=config.processing.spectrum_max_hz,
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
        worker_pool=worker_pool,
    )
    ws_hub = WebSocketHub()
    control_plane = UDPControlPlane(
        registry=registry,
        bind_host=config.udp.control_host,
        bind_port=config.udp.control_port,
    )
    gps_monitor = GPSSpeedMonitor(gps_enabled=config.gps.gps_enabled)
    analysis_settings = AnalysisSettingsStore()
    settings_store = SettingsStore(db=history_db)
    metrics_logger = MetricsLogger(
        enabled=config.logging.log_metrics,
        log_path=config.logging.metrics_log_path,
        metrics_log_hz=config.logging.metrics_log_hz,
        no_data_timeout_s=config.logging.no_data_timeout_s,
        registry=registry,
        gps_monitor=gps_monitor,
        processor=processor,
        analysis_settings=analysis_settings,
        sensor_model=config.logging.sensor_model,
        default_sample_rate_hz=config.processing.sample_rate_hz,
        fft_window_size_samples=config.processing.fft_n,
        fft_window_type="hann",
        peak_picker_method="canonical_strength_metrics_module",
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
        history_db=history_db,
        persist_history_db=config.logging.persist_history_db,
        language_provider=lambda: settings_store.language,
    )

    # Re-queue runs stuck in 'analyzing' state (e.g. after a crash)
    stale_analyzing = history_db.stale_analyzing_run_ids()
    for stale_run_id in stale_analyzing:
        LOGGER.info("Re-queuing stuck analyzing run %s for re-analysis", stale_run_id)
        metrics_logger._schedule_post_analysis(stale_run_id)
    if stale_analyzing:
        LOGGER.info("Re-queued %d stuck analyzing run(s)", len(stale_analyzing))

    live_diagnostics = LiveDiagnosticsEngine()
    update_manager = UpdateManager()
    esp_flash_manager = EspFlashManager()

    runtime = RuntimeState(
        config=config,
        registry=registry,
        processor=processor,
        control_plane=control_plane,
        ws_hub=ws_hub,
        gps_monitor=gps_monitor,
        analysis_settings=analysis_settings,
        metrics_logger=metrics_logger,
        live_diagnostics=live_diagnostics,
        settings_store=settings_store,
        history_db=history_db,
        update_manager=update_manager,
        esp_flash_manager=esp_flash_manager,
    )
    # Sync initial settings into analysis store and GPS monitor
    runtime.apply_car_settings()
    runtime.apply_speed_source_settings()

    async def processing_loop() -> None:
        interval = 1.0 / max(1, config.processing.fft_update_hz)
        consecutive_failures = 0
        _sync_clock_tick = 0
        _SYNC_CLOCK_EVERY_N_TICKS = max(1, int(5.0 / interval))  # ~every 5 s
        while True:
            try:
                _sync_clock_tick += 1
                if _sync_clock_tick >= _SYNC_CLOCK_EVERY_N_TICKS:
                    _sync_clock_tick = 0
                    if runtime.control_plane is not None:
                        runtime.control_plane.broadcast_sync_clock()
                runtime.registry.evict_stale()
                active_ids = runtime.registry.active_client_ids()
                # Only recompute metrics for clients that received new data
                # since the last tick.  This prevents stale ring-buffer data
                # from cycling through the pipeline indefinitely.
                fresh_ids = runtime.processor.clients_with_recent_data(
                    active_ids, max_age_s=STALE_DATA_AGE_S
                )
                sample_rates: dict[str, int] = {}
                for client_id in fresh_ids:
                    record = runtime.registry.get(client_id)
                    if record is None:
                        continue
                    sample_rates[client_id] = record.sample_rate_hz
                    client_rate = int(record.sample_rate_hz or 0)
                    default_rate = runtime.config.processing.sample_rate_hz
                    if (
                        client_rate > 0
                        and client_rate != default_rate
                        and client_id not in runtime.sample_rate_mismatch_logged
                    ):
                        runtime.sample_rate_mismatch_logged.add(client_id)
                        LOGGER.warning(
                            "Client %s uses sample_rate_hz=%d; default config is %d.",
                            client_id,
                            client_rate,
                            default_rate,
                        )
                    frame_samples = int(record.frame_samples or 0)
                    if (
                        frame_samples > 0
                        and frame_samples > runtime.config.processing.fft_n
                        and client_id not in runtime.frame_size_mismatch_logged
                    ):
                        runtime.frame_size_mismatch_logged.add(client_id)
                        LOGGER.error(
                            "Client %s reported frame_samples=%d larger than fft_n=%d; "
                            "ingest may be degraded.",
                            client_id,
                            frame_samples,
                            runtime.config.processing.fft_n,
                        )
                metrics_by_client = await asyncio.to_thread(
                    runtime.processor.compute_all,
                    fresh_ids,
                    sample_rates_hz=sample_rates,
                )
                for client_id, metrics in metrics_by_client.items():
                    runtime.registry.set_latest_metrics(client_id, metrics)
                runtime.processor.evict_clients(set(active_ids))
                consecutive_failures = 0
                runtime.processing_state = "ok"
            except Exception:
                consecutive_failures += 1
                runtime.processing_failure_count += 1
                is_fatal = consecutive_failures >= MAX_CONSECUTIVE_FAILURES
                runtime.processing_state = "fatal" if is_fatal else "degraded"
                LOGGER.warning("Processing loop tick failed; will retry.", exc_info=True)
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    LOGGER.error(
                        "Processing loop hit %d failures; backing off %d s then resetting",
                        MAX_CONSECUTIVE_FAILURES,
                        FAILURE_BACKOFF_S,
                    )
                    await asyncio.sleep(FAILURE_BACKOFF_S)
                    consecutive_failures = 0
                    runtime.processing_state = "degraded"
            delay = (
                interval
                if consecutive_failures == 0
                else min(5.0, interval * (2 ** min(6, consecutive_failures)))
            )
            await asyncio.sleep(delay)

    async def start_runtime() -> None:
        runtime.data_transport, runtime.data_consumer_task = await start_udp_data_receiver(
            host=config.udp.data_host,
            port=config.udp.data_port,
            registry=runtime.registry,
            processor=runtime.processor,
            queue_maxsize=config.udp.data_queue_maxsize,
        )
        await runtime.control_plane.start()
        runtime.tasks = [
            asyncio.create_task(processing_loop(), name="processing-loop"),
            asyncio.create_task(
                runtime.ws_hub.run(
                    config.processing.ui_push_hz,
                    runtime.build_ws_payload,
                    on_tick=runtime.on_ws_broadcast_tick,
                ),
                name="ws-broadcast",
            ),
            asyncio.create_task(runtime.metrics_logger.run(), name="metrics-log"),
            asyncio.create_task(runtime.gps_monitor.run(), name="gps-speed"),
        ]
        # Recover interrupted update jobs (best-effort, must not crash server)
        runtime.tasks.append(
            asyncio.create_task(
                runtime.update_manager.startup_recover(),
                name="update-startup-recover",
            )
        )

    async def stop_runtime() -> None:
        for task in runtime.tasks:
            task.cancel()
        await asyncio.gather(*runtime.tasks, return_exceptions=True)
        runtime.tasks.clear()

        runtime.metrics_logger.stop_logging()
        analysis_timeout_s = config.logging.shutdown_analysis_timeout_s
        finished = await asyncio.to_thread(
            runtime.metrics_logger.wait_for_post_analysis, analysis_timeout_s
        )
        if not finished:
            LOGGER.warning(
                "Post-analysis did not finish within %.1fs on shutdown; "
                "results for the last run may be lost.",
                analysis_timeout_s,
            )

        try:
            runtime.control_plane.close()
        except Exception:
            LOGGER.warning("Error closing control plane", exc_info=True)
        try:
            if runtime.data_transport is not None:
                runtime.data_transport.close()
                runtime.data_transport = None
        except Exception:
            LOGGER.warning("Error closing data transport", exc_info=True)
        if runtime.data_consumer_task is not None:
            runtime.data_consumer_task.cancel()
            await asyncio.gather(runtime.data_consumer_task, return_exceptions=True)
            runtime.data_consumer_task = None
        try:
            await asyncio.to_thread(worker_pool.shutdown, True)
        except Exception:
            LOGGER.warning("Error shutting down worker pool", exc_info=True)
        try:
            runtime.history_db.close()
        except Exception:
            LOGGER.warning("Error closing history DB", exc_info=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await start_runtime()
        try:
            yield
        finally:
            await stop_runtime()

    app = FastAPI(title="VibeSensor", lifespan=lifespan)
    app.state.runtime = runtime
    app.include_router(create_router(runtime))
    if os.getenv("VIBESENSOR_SERVE_STATIC", "1") == "1":
        # Prefer packaged static assets (baked into the wheel by CI), then
        # fall back to the legacy ``apps/server/public/`` directory used by
        # Docker builds and local development.
        packaged_static = Path(__file__).resolve().parent / "static"
        legacy_public = SERVER_DIR / "public"
        if (packaged_static / "index.html").exists():
            static_dir = packaged_static
        elif (legacy_public / "index.html").exists():
            static_dir = legacy_public
        else:
            message = (
                "UI not built. Run tools/sync_ui_to_pi_public.py, "
                "build the Docker image, or install a release wheel."
            )
            LOGGER.error(
                "%s Missing index.html in %s and %s",
                message,
                packaged_static,
                legacy_public,
            )
            raise RuntimeError(message)
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="public")

    return app


app: FastAPI | None = (
    create_app()
    if __name__ != "__main__" and os.getenv("VIBESENSOR_DISABLE_AUTO_APP", "0") != "1"
    else None
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run VibeSensor server")
    parser.add_argument("--config", type=Path, default=None, help="Path to config YAML")
    args = parser.parse_args()

    runtime_app = create_app(config_path=args.config)
    runtime: RuntimeState = runtime_app.state.runtime
    host = runtime.config.server.host
    port = runtime.config.server.port
    try:
        uvicorn.run(
            runtime_app,
            host=host,
            port=port,
            log_level="info",
        )
    except OSError as exc:
        bind_error_numbers = {errno.EACCES, errno.EADDRINUSE, 10013, 10048}
        if port != 80:
            LOGGER.warning("Failed to bind to configured port %d.", port, exc_info=True)
            raise
        if exc.errno not in bind_error_numbers:
            LOGGER.warning("Port 80 startup failed with non-bind OSError.", exc_info=True)
            raise
        LOGGER.warning(
            "Failed to bind to port 80; retrying on backup port %d.",
            BACKUP_SERVER_PORT,
            exc_info=True,
        )
        try:
            uvicorn.run(
                runtime_app,
                host=host,
                port=BACKUP_SERVER_PORT,
                log_level="info",
            )
        except OSError:
            LOGGER.error(
                "Failed to bind to both port 80 and backup port %d.",
                BACKUP_SERVER_PORT,
                exc_info=True,
            )
            raise


if __name__ == "__main__":
    main()
