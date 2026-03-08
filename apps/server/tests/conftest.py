"""Shared test fixtures and helpers for the vibesensor test suite.

Plain helper functions / assertion utilities live in
``_test_helpers.py`` so they can be imported unambiguously even when
sub-directory ``conftest.py`` files exist (which shadow this module in
``sys.modules``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from vibesensor.runtime import ProcessingLoopState

# ---------------------------------------------------------------------------
# Shared API test helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeState:
    """Minimal stand-in for RuntimeState used by ``create_router``."""

    config: object = field(default_factory=MagicMock)
    registry: object = field(default_factory=MagicMock)
    processor: object = field(default_factory=MagicMock)
    control_plane: object = field(default_factory=MagicMock)
    ws_hub: object = field(default_factory=MagicMock)
    gps_monitor: object = field(default_factory=MagicMock)
    analysis_settings: object = field(default_factory=MagicMock)
    metrics_logger: object = field(default_factory=MagicMock)
    live_diagnostics: object = field(default_factory=MagicMock)
    settings_store: object = field(default_factory=MagicMock)
    history_db: object = field(default_factory=MagicMock)
    update_manager: object = field(default_factory=MagicMock)
    esp_flash_manager: object = field(default_factory=MagicMock)
    loop_state: ProcessingLoopState = field(default_factory=ProcessingLoopState)
    apply_car_settings: object = field(default_factory=MagicMock)
    apply_speed_source_settings: object = field(default_factory=MagicMock)

    def __post_init__(self) -> None:
        self.ingress = SimpleNamespace(
            registry=self.registry,
            processor=self.processor,
            control_plane=self.control_plane,
        )
        self.settings = SimpleNamespace(
            settings_store=self.settings_store,
            gps_monitor=self.gps_monitor,
            analysis_settings=self.analysis_settings,
            apply_car_settings=self.apply_car_settings,
            apply_speed_source_settings=self.apply_speed_source_settings,
        )
        self.diagnostics = SimpleNamespace(
            metrics_logger=self.metrics_logger,
            live_diagnostics=self.live_diagnostics,
        )
        self.persistence = SimpleNamespace(history_db=self.history_db)
        self.websocket = SimpleNamespace(hub=self.ws_hub)
        self.updates = SimpleNamespace(
            update_manager=self.update_manager,
            esp_flash_manager=self.esp_flash_manager,
        )
        self.processing = SimpleNamespace(state=self.loop_state)


@pytest.fixture
def fake_state() -> FakeState:
    """Return a fresh ``FakeState`` for each test."""
    state = FakeState()
    state.processor.intake_stats.return_value = {
        "total_ingested_samples": 0,
        "total_compute_calls": 0,
        "last_compute_duration_s": 0.0,
        "last_compute_all_duration_s": 0.0,
        "last_ingest_duration_s": 0.0,
    }
    state.registry.data_loss_snapshot.return_value = {
        "tracked_clients": 0,
        "affected_clients": 0,
        "frames_dropped": 0,
        "queue_overflow_drops": 0,
        "server_queue_drops": 0,
        "parse_errors": 0,
    }
    state.metrics_logger.health_snapshot.return_value = {
        "write_error": None,
        "analysis_in_progress": False,
        "analysis_queue_depth": 0,
        "analysis_queue_max_depth": 0,
        "analysis_active_run_id": None,
        "analysis_started_at": None,
        "analysis_elapsed_s": None,
        "analysis_queue_oldest_age_s": None,
        "analyzing_run_count": 0,
        "analyzing_oldest_age_s": None,
    }
    return state


@pytest.fixture
def route_paths(fake_state: FakeState) -> set[str]:
    """All registered URL paths from the assembled router."""
    from vibesensor.routes import create_router

    router = create_router(fake_state)
    return {r.path for r in router.routes}
