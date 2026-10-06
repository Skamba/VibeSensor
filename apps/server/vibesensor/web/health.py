"""Health check endpoint."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter

from vibesensor.ingest.diagnostics import IngestDiagnosticsCollector
from vibesensor.web.health_snapshot import build_system_health_snapshot
from vibesensor.web.models.health import HealthResponse

if TYPE_CHECKING:
    from vibesensor.ingest.registry import ClientRegistry
    from vibesensor.live.processing_loop import ProcessingLoopState
    from vibesensor.live.processor import SignalProcessor
    from vibesensor.power.monitor import PowerMonitor
    from vibesensor.recording.recorder import RunRecorder
    from vibesensor.updates.firmware.esp_flash_manager import EspFlashManager
    from vibesensor.web.health_state import RuntimeHealthState


def create_health_routes(
    loop_state: ProcessingLoopState,
    health_state: RuntimeHealthState,
    processor: SignalProcessor,
    registry: ClientRegistry,
    run_recorder: RunRecorder,
    ingest_diagnostics: IngestDiagnosticsCollector,
    esp_flash_manager: EspFlashManager,
    power_monitor: PowerMonitor,
) -> APIRouter:
    """Create and return the health-check API routes."""
    router = APIRouter(tags=["health"])

    @router.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """Return the current runtime health snapshot for the server and sensor pipeline."""
        return HealthResponse.model_validate(
            await asyncio.to_thread(
                build_system_health_snapshot,
                loop_state,
                health_state,
                processor,
                registry,
                run_recorder,
                ingest_diagnostics,
                esp_flash_manager.bundled_firmware_version(),
                power_monitor.snapshot(),
            )
        )

    return router
