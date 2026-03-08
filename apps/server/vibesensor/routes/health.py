"""Health check endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from ..api_models import HealthResponse

if TYPE_CHECKING:
    from ..metrics_log import MetricsLogger
    from ..processing import SignalProcessor
    from ..registry import ClientRegistry
    from ..runtime.health_state import RuntimeHealthState
    from ..runtime.processing_loop import ProcessingLoopState


def create_health_routes(
    loop_state: ProcessingLoopState,
    health_state: RuntimeHealthState,
    processor: SignalProcessor,
    registry: ClientRegistry,
    metrics_logger: MetricsLogger,
) -> APIRouter:
    """Create and return the health-check API routes."""
    router = APIRouter()

    @router.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        failures = loop_state.processing_failure_count
        data_loss = registry.data_loss_snapshot()
        persistence = metrics_logger.health_snapshot()
        failure_categories = dict(loop_state.processing_failure_categories)
        sample_rate_mismatch_count = len(loop_state.sample_rate_mismatch_logged)
        frame_size_mismatch_count = len(loop_state.frame_size_mismatch_logged)
        degradation_reasons: list[str] = []
        if health_state.startup_state != "ready":
            degradation_reasons.append(f"startup_state:{health_state.startup_state}")
        if health_state.startup_error:
            degradation_reasons.append("startup_error")
        if health_state.background_task_failures:
            degradation_reasons.append("background_task_failures")
        if loop_state.processing_state != "ok":
            degradation_reasons.append(f"processing_state:{loop_state.processing_state}")
        if failures > 0:
            degradation_reasons.append("processing_failures")
        if loop_state.last_failure_category:
            degradation_reasons.append(f"processing_failure:{loop_state.last_failure_category}")
        if sample_rate_mismatch_count > 0:
            degradation_reasons.append("sample_rate_mismatch")
        if frame_size_mismatch_count > 0:
            degradation_reasons.append("frame_size_mismatch")
        for key in (
            "frames_dropped",
            "queue_overflow_drops",
            "server_queue_drops",
            "parse_errors",
        ):
            if data_loss[key] > 0:
                degradation_reasons.append(key)
        if persistence["write_error"]:
            degradation_reasons.append("persistence_write_error")
        if persistence["analyzing_run_count"] > 0:
            degradation_reasons.append("analyzing_runs_present")
        return {
            "status": "ok" if not degradation_reasons else "degraded",
            "startup_state": health_state.startup_state,
            "startup_phase": health_state.startup_phase,
            "startup_error": health_state.startup_error,
            "background_task_failures": dict(health_state.background_task_failures),
            "processing_state": loop_state.processing_state,
            "processing_failures": failures,
            "processing_failure_categories": failure_categories,
            "processing_last_failure": loop_state.last_failure_message,
            "sample_rate_mismatch_count": sample_rate_mismatch_count,
            "frame_size_mismatch_count": frame_size_mismatch_count,
            "degradation_reasons": degradation_reasons,
            "data_loss": data_loss,
            "persistence": persistence,
            "intake_stats": processor.intake_stats(),
        }

    return router
