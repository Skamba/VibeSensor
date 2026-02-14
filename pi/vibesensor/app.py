from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import create_router
from .config import PI_DIR, AppConfig, load_config
from .gps_speed import GPSSpeedMonitor
from .metrics_log import MetricsLogger
from .processing import SignalProcessor
from .registry import ClientRegistry
from .udp_control_tx import UDPControlPlane
from .udp_data_rx import start_udp_data_receiver
from .ws_hub import WebSocketHub


@dataclass(slots=True)
class RuntimeState:
    config: AppConfig
    registry: ClientRegistry
    processor: SignalProcessor
    control_plane: UDPControlPlane
    ws_hub: WebSocketHub
    gps_monitor: GPSSpeedMonitor
    metrics_logger: MetricsLogger
    tasks: list[asyncio.Task] = field(default_factory=list)
    data_transport: asyncio.DatagramTransport | None = None

    def build_ws_payload(self, selected_client: str | None) -> dict[str, Any]:
        clients = self.registry.snapshot_for_api()
        active = selected_client
        if active is None and clients:
            active = clients[0]["id"]
        client_ids = [c["id"] for c in clients]

        payload: dict[str, Any] = {
            "server_time": datetime.now(UTC).isoformat(),
            "speed_mps": self.gps_monitor.speed_mps,
            "clients": clients,
            "selected_client_id": active,
            "spectra": self.processor.multi_spectrum_payload(client_ids),
        }
        if active is not None:
            payload["selected"] = self.processor.selected_payload(active)
        else:
            payload["selected"] = {}
        return payload


def create_app(config_path: Path | None = None) -> FastAPI:
    config = load_config(config_path)
    config.logging.metrics_csv_path.parent.mkdir(parents=True, exist_ok=True)
    config.clients_json_path.parent.mkdir(parents=True, exist_ok=True)

    registry = ClientRegistry(config.clients_json_path)
    processor = SignalProcessor(
        sample_rate_hz=config.processing.sample_rate_hz,
        waveform_seconds=config.processing.waveform_seconds,
        waveform_display_hz=config.processing.waveform_display_hz,
        fft_n=config.processing.fft_n,
        spectrum_max_hz=config.processing.spectrum_max_hz,
    )
    ws_hub = WebSocketHub()
    control_plane = UDPControlPlane(
        registry=registry,
        bind_host=config.udp.control_host,
        bind_port=config.udp.control_port,
    )
    gps_monitor = GPSSpeedMonitor(gps_enabled=config.gps.gps_enabled)
    metrics_logger = MetricsLogger(
        enabled=config.logging.log_metrics,
        csv_path=config.logging.metrics_csv_path,
        metrics_log_hz=config.logging.metrics_log_hz,
        registry=registry,
        gps_monitor=gps_monitor,
    )

    runtime = RuntimeState(
        config=config,
        registry=registry,
        processor=processor,
        control_plane=control_plane,
        ws_hub=ws_hub,
        gps_monitor=gps_monitor,
        metrics_logger=metrics_logger,
    )

    app = FastAPI(title="VibeSensor")
    app.state.runtime = runtime
    app.include_router(create_router(runtime))
    app.mount("/", StaticFiles(directory=PI_DIR / "public", html=True), name="public")

    @app.on_event("startup")
    async def on_startup() -> None:
        runtime.data_transport = await start_udp_data_receiver(
            host=config.udp.data_host,
            port=config.udp.data_port,
            registry=runtime.registry,
            processor=runtime.processor,
        )
        await runtime.control_plane.start()

        async def processing_loop() -> None:
            interval = 1.0 / max(1, config.processing.fft_update_hz)
            while True:
                metrics_by_client = runtime.processor.compute_all(runtime.registry.client_ids())
                for client_id, metrics in metrics_by_client.items():
                    runtime.registry.set_latest_metrics(client_id, metrics)
                await asyncio.sleep(interval)

        runtime.tasks = [
            asyncio.create_task(processing_loop(), name="processing-loop"),
            asyncio.create_task(
                runtime.ws_hub.run(config.processing.ui_push_hz, runtime.build_ws_payload),
                name="ws-broadcast",
            ),
            asyncio.create_task(runtime.metrics_logger.run(), name="metrics-log"),
            asyncio.create_task(runtime.gps_monitor.run(), name="gps-speed"),
        ]

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        for task in runtime.tasks:
            task.cancel()
        await asyncio.gather(*runtime.tasks, return_exceptions=True)
        runtime.tasks.clear()

        runtime.control_plane.close()
        if runtime.data_transport is not None:
            runtime.data_transport.close()
            runtime.data_transport = None

    return app


app = create_app()


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


