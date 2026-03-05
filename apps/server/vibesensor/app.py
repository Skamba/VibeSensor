"""FastAPI application factory and CLI entry point.

This module wires services together and creates the FastAPI application.
The ``RuntimeState`` class that owns lifecycle, processing loop, and
WS-payload assembly now lives in ``runtime.py``.  It is re-exported here
for backward compatibility so that ``from vibesensor.app import RuntimeState``
continues to work.
"""

from __future__ import annotations

import argparse
import errno
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from vibesensor_core.sensor_units import get_accel_scale_g_per_lsb

from .analysis_settings import AnalysisSettingsStore
from .config import SERVER_DIR, load_config
from .esp_flash_manager import EspFlashManager
from .gps_speed import GPSSpeedMonitor
from .history_db import HistoryDB
from .live_diagnostics import LiveDiagnosticsEngine
from .metrics_log import MetricsLogger, MetricsLoggerConfig
from .processing import SignalProcessor
from .registry import ClientRegistry
from .routes import create_router
from .runtime import RuntimeState
from .settings_store import SettingsStore
from .udp_control_tx import UDPControlPlane
from .update.manager import UpdateManager
from .worker_pool import WorkerPool
from .ws_hub import WebSocketHub

__all__ = ["RuntimeState", "create_app", "main"]

LOGGER = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).resolve().parent
"""Resolved directory containing this package, cached at import time to avoid
repeated filesystem resolution in ``create_app()``."""

BACKUP_SERVER_PORT = 8000
"""Fallback HTTP port when the configured port is unavailable (e.g. EACCES
on port 80).  Chosen to be a common unprivileged alternative."""

_BIND_ERROR_NUMBERS: frozenset[int] = frozenset({errno.EACCES, errno.EADDRINUSE, 10013, 10048})
"""OS errno values indicating a port-bind failure (includes Windows equivalents)."""


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
        MetricsLoggerConfig(
            enabled=config.logging.log_metrics,
            log_path=config.logging.metrics_log_path,
            metrics_log_hz=config.logging.metrics_log_hz,
            no_data_timeout_s=config.logging.no_data_timeout_s,
            sensor_model=config.logging.sensor_model,
            default_sample_rate_hz=config.processing.sample_rate_hz,
            fft_window_size_samples=config.processing.fft_n,
            fft_window_type="hann",
            peak_picker_method="canonical_strength_metrics_module",
            accel_scale_g_per_lsb=accel_scale_g_per_lsb,
            persist_history_db=config.logging.persist_history_db,
        ),
        registry=registry,
        gps_monitor=gps_monitor,
        processor=processor,
        analysis_settings=analysis_settings,
        history_db=history_db,
        language_provider=lambda: settings_store.language,
    )

    # Re-queue runs stuck in 'analyzing' state (e.g. after a crash)
    stale_analyzing = history_db.stale_analyzing_run_ids()
    for stale_run_id in stale_analyzing:
        LOGGER.info("Re-queuing stuck analyzing run %s for re-analysis", stale_run_id)
        metrics_logger.schedule_post_analysis(stale_run_id)
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
        worker_pool=worker_pool,
    )
    # Sync initial settings into analysis store and GPS monitor
    runtime.apply_car_settings()
    runtime.apply_speed_source_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(title="VibeSensor", lifespan=lifespan)
    app.state.runtime = runtime
    app.include_router(create_router(runtime))
    if os.getenv("VIBESENSOR_SERVE_STATIC", "1") == "1":
        # Prefer packaged static assets (baked into the wheel by CI), then
        # fall back to the legacy ``apps/server/public/`` directory used by
        # Docker builds and local development.
        packaged_static = _PACKAGE_DIR / "static"
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
        if port != 80:
            LOGGER.warning("Failed to bind to configured port %d.", port, exc_info=True)
            raise
        if exc.errno not in _BIND_ERROR_NUMBERS:
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
