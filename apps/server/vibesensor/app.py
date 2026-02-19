"""Runtime orchestration for ingestion -> processing -> diagnostics -> WS/API.

Boundary note for maintainers:
- Keep this module focused on orchestration, not algorithm details.
- Metric math belongs in `processing.py` / `analysis/*`.
- API schemas belong in `api.py` and must remain backward-compatible.
"""

from __future__ import annotations

import argparse
import asyncio
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

from .analysis_settings import AnalysisSettingsStore
from .api import create_router
from .config import PI_DIR, AppConfig, load_config
from .gps_speed import GPSSpeedMonitor
from .history_db import HistoryDB
from .live_diagnostics import LiveDiagnosticsEngine
from .metrics_log import MetricsLogger
from .processing import SignalProcessor
from .registry import ClientRegistry
from .sensor_units import get_accel_scale_g_per_lsb
from .settings_store import SettingsStore
from .udp_control_tx import UDPControlPlane
from .udp_data_rx import start_udp_data_receiver
from .ws_hub import WebSocketHub

LOGGER = logging.getLogger(__name__)


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
    tasks: list[asyncio.Task] = field(default_factory=list)
    data_transport: asyncio.DatagramTransport | None = None
    data_consumer_task: asyncio.Task | None = None
    sample_rate_mismatch_logged: set[str] = field(default_factory=set)
    frame_size_mismatch_logged: set[str] = field(default_factory=set)
    processing_state: str = "ok"
    processing_failure_count: int = 0
    ws_tick: int = 0
    ws_include_heavy: bool = True

    def on_ws_broadcast_tick(self) -> None:
        self.ws_tick += 1
        heavy_every = max(
            1,
            int(
                self.config.processing.ui_push_hz / max(1, self.config.processing.ui_heavy_push_hz)
            ),
        )
        self.ws_include_heavy = (self.ws_tick % heavy_every) == 0

    def build_ws_payload(self, selected_client: str | None) -> dict[str, Any]:
        clients = self.registry.snapshot_for_api()
        active = selected_client
        if active is None and clients:
            active = clients[0]["id"]
        client_ids = [c["id"] for c in clients]
        # Only include spectrum data for clients with recent UDP data
        # to prevent stale buffer data from driving diagnostics/events.
        fresh_ids = self.processor.clients_with_recent_data(client_ids, max_age_s=3.0)

        payload: dict[str, Any] = {
            "server_time": datetime.now(UTC).isoformat(),
            "speed_mps": self.gps_monitor.effective_speed_mps,
            "clients": clients,
            "selected_client_id": active,
        }
        analysis_settings_snapshot = self.analysis_settings.snapshot()
        analysis_metadata, analysis_samples = self.metrics_logger.analysis_snapshot()
        if self.ws_include_heavy:
            payload["spectra"] = self.processor.multi_spectrum_payload(fresh_ids)
            if active is not None and active in fresh_ids:
                payload["selected"] = self.processor.selected_payload(active)
            else:
                payload["selected"] = {}
            payload["diagnostics"] = self.live_diagnostics.update(
                speed_mps=self.gps_monitor.effective_speed_mps,
                clients=clients,
                spectra=payload.get("spectra"),
                settings=analysis_settings_snapshot,
                finding_metadata=analysis_metadata,
                finding_samples=analysis_samples,
                language=self.settings_store.language,
            )
        else:
            payload["diagnostics"] = self.live_diagnostics.update(
                speed_mps=self.gps_monitor.effective_speed_mps,
                clients=clients,
                spectra=None,
                settings=analysis_settings_snapshot,
                finding_metadata=analysis_metadata,
                finding_samples=analysis_samples,
                language=self.settings_store.language,
            )
        return payload


def create_app(config_path: Path | None = None) -> FastAPI:
    config = load_config(config_path)

    registry = ClientRegistry(
        config.clients_json_path,
        stale_ttl_seconds=config.processing.client_ttl_seconds,
    )
    accel_scale_g_per_lsb = (
        config.processing.accel_scale_g_per_lsb
        if config.processing.accel_scale_g_per_lsb is not None
        else get_accel_scale_g_per_lsb(config.logging.sensor_model)
    )
    processor = SignalProcessor(
        sample_rate_hz=config.processing.sample_rate_hz,
        waveform_seconds=config.processing.waveform_seconds,
        waveform_display_hz=config.processing.waveform_display_hz,
        fft_n=config.processing.fft_n,
        spectrum_max_hz=config.processing.spectrum_max_hz,
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
    )
    ws_hub = WebSocketHub()
    control_plane = UDPControlPlane(
        registry=registry,
        bind_host=config.udp.control_host,
        bind_port=config.udp.control_port,
    )
    gps_monitor = GPSSpeedMonitor(gps_enabled=config.gps.gps_enabled)
    analysis_settings = AnalysisSettingsStore()
    settings_persist = config.clients_json_path.parent / "settings.json"
    settings_store = SettingsStore(persist_path=settings_persist)
    # Sync initial settings into analysis store and GPS monitor
    analysis_settings.update(settings_store.active_car_aspects())
    ss = settings_store.get_speed_source()
    if ss["speedSource"] == "manual" and ss["manualSpeedKph"] is not None:
        gps_monitor.set_speed_override_kmh(ss["manualSpeedKph"])
    history_db = HistoryDB(config.logging.history_db_path)
    metrics_logger = MetricsLogger(
        enabled=config.logging.log_metrics,
        log_path=config.logging.metrics_log_path,
        metrics_log_hz=config.logging.metrics_log_hz,
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
    )
    live_diagnostics = LiveDiagnosticsEngine()

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
    )

    async def processing_loop() -> None:
        interval = 1.0 / max(1, config.processing.fft_update_hz)
        consecutive_failures = 0
        while True:
            try:
                runtime.registry.evict_stale()
                active_ids = runtime.registry.active_client_ids()
                # Only recompute metrics for clients that received new data
                # since the last tick.  This prevents stale ring-buffer data
                # from cycling through the pipeline indefinitely.
                fresh_ids = runtime.processor.clients_with_recent_data(active_ids, max_age_s=3.0)
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
                metrics_by_client = runtime.processor.compute_all(
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
                runtime.processing_state = "degraded" if consecutive_failures < 25 else "fatal"
                LOGGER.warning("Processing loop tick failed; will retry.", exc_info=True)
                if consecutive_failures >= 25:
                    LOGGER.error("Processing loop entered fatal state after repeated failures")
                    return
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

    async def stop_runtime() -> None:
        for task in runtime.tasks:
            task.cancel()
        await asyncio.gather(*runtime.tasks, return_exceptions=True)
        runtime.tasks.clear()

        runtime.metrics_logger.stop_logging()

        runtime.control_plane.close()
        if runtime.data_transport is not None:
            runtime.data_transport.close()
            runtime.data_transport = None
        if runtime.data_consumer_task is not None:
            runtime.data_consumer_task.cancel()
            await asyncio.gather(runtime.data_consumer_task, return_exceptions=True)
            runtime.data_consumer_task = None

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
        public_index = PI_DIR / "public" / "index.html"
        if not public_index.exists():
            message = "UI not built. Run tools/sync_ui_to_pi_public.py or build the Docker image."
            LOGGER.error("%s Missing file: %s", message, public_index)
            raise RuntimeError(message)
        app.mount("/", StaticFiles(directory=PI_DIR / "public", html=True), name="public")

    return app


app: FastAPI | None = create_app() if __name__ != "__main__" else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Run VibeSensor server")
    parser.add_argument("--config", type=Path, default=None, help="Path to config YAML")
    args = parser.parse_args()

    runtime_app = create_app(config_path=args.config)
    runtime: RuntimeState = runtime_app.state.runtime
    uvicorn.run(
        runtime_app,
        host=runtime.config.server.host,
        port=runtime.config.server.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
