"""Shared test fixtures and helpers for the vibesensor test suite.

Plain helper functions / assertion utilities live in
``_test_helpers.py`` so they can be imported unambiguously even when
sub-directory ``conftest.py`` files exist (which shadow this module in
``sys.modules``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

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
    processing_state: str = "idle"
    processing_failure_count: int = 0
    apply_car_settings: object = field(default_factory=MagicMock)
    apply_speed_source_settings: object = field(default_factory=MagicMock)


@pytest.fixture
def fake_state() -> FakeState:
    """Return a fresh ``FakeState`` for each test."""
    return FakeState()


@pytest.fixture
def route_paths(fake_state: FakeState) -> set[str]:
    """All registered URL paths from the assembled router."""
    from vibesensor.routes import create_router

    router = create_router(fake_state)
    return {r.path for r in router.routes}
