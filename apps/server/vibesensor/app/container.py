from __future__ import annotations

from collections.abc import Callable

from vibesensor.adapters.persistence.history_db import (
    HistoryPersistenceAdapters,
    create_history_persistence_adapters,
)
from vibesensor.app.composition.history import (
    HistoryServiceBundle,
    build_history_service_bundle,
)
from vibesensor.app.composition.history import (
    create_history_db as _create_history_db,
)
from vibesensor.app.composition.live import (
    LiveRuntimeBundle,
    build_live_runtime,
    resolve_accel_scale_g_per_lsb,
)
from vibesensor.app.composition.runtime import build_lifecycle_state, build_router_deps
from vibesensor.app.composition.settings import (
    RuntimeSettingsDeps,
    SettingsServiceBundle,
    build_settings_service_bundle,
)
from vibesensor.app.composition.speed import (
    SpeedRuntimeBundle,
    build_speed_runtime,
)
from vibesensor.app.composition.updates import build_update_deps
from vibesensor.app.config_schema import AppConfig
from vibesensor.app.runtime_state import AppRuntime
from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.shared.boundaries.reporting.document import ReportDocument

__all__ = [
    "HistoryServiceBundle",
    "LiveRuntimeBundle",
    "RuntimeSettingsDeps",
    "SettingsServiceBundle",
    "SpeedRuntimeBundle",
    "build_history_service_bundle",
    "build_lifecycle_state",
    "build_live_runtime",
    "build_router_deps",
    "build_runtime",
    "build_settings_service_bundle",
    "build_speed_runtime",
    "build_update_deps",
    "create_history_db",
    "resolve_accel_scale_g_per_lsb",
]


def _build_pdf_bytes(document: ReportDocument) -> bytes:
    """Render a prepared report document through the PDF adapter boundary."""
    from vibesensor.adapters.pdf.pdf_engine import build_report_pdf

    return build_report_pdf(document)


def create_history_db(
    config: AppConfig,
    *,
    corruption_reporter: Callable[[str], None] | None = None,
    engine_failure_reporter: Callable[[str, str], None] | None = None,
) -> HistoryPersistenceAdapters:
    """Create and initialise the shared history persistence collaborators."""

    return _create_history_db(
        config,
        corruption_reporter=corruption_reporter,
        engine_failure_reporter=engine_failure_reporter,
        adapter_factory=create_history_persistence_adapters,
    )


def build_runtime(config: AppConfig) -> AppRuntime:
    """Construct all services and return the app runtime bundle."""
    accel_scale_g_per_lsb = resolve_accel_scale_g_per_lsb(config)
    health_state = RuntimeHealthState()

    history = create_history_db(
        config,
        corruption_reporter=health_state.mark_db_corrupted,
        engine_failure_reporter=health_state.mark_db_engine_unhealthy,
    )
    speed_runtime = build_speed_runtime(config)
    settings_services = build_settings_service_bundle(
        snapshot_repository=history.settings_snapshot_repository,
        speed_control=speed_runtime.speed_services.control,
    )
    runtime_settings = settings_services.runtime_deps()
    history_services = build_history_service_bundle(
        history=history,
        current_car_reader=settings_services.settings_reader,
    )
    live_runtime = build_live_runtime(
        config=config,
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
        history=history,
        speed_runtime=speed_runtime,
        runtime_settings=runtime_settings,
    )
    updates = build_update_deps(config)
    lifecycle = build_lifecycle_state(
        config=config,
        health_state=health_state,
        history=history,
        speed_runtime=speed_runtime,
        runtime_settings=runtime_settings,
        live_runtime=live_runtime,
        updates=updates,
    )
    router = build_router_deps(
        health_state=health_state,
        speed_runtime=speed_runtime,
        settings_services=settings_services,
        history_services=history_services,
        live_runtime=live_runtime,
        updates=updates,
    )
    settings_services.speed_source_service.sync_all()
    return AppRuntime(lifecycle=lifecycle, router=router)
