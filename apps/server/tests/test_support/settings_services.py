"""Shared builders for focused persisted settings service bundles in tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vibesensor.infra.config.analysis_settings import ActiveCarAnalysisSettingsService
from vibesensor.infra.config.car_settings import CarSettingsService
from vibesensor.infra.config.sensor_settings import SensorSettingsService
from vibesensor.infra.config.settings_derivation import SettingsDerivationService
from vibesensor.infra.config.settings_persistence import SettingsPersistenceCoordinator
from vibesensor.infra.config.speed_source_settings import PersistedSpeedSourceSettingsService
from vibesensor.infra.config.ui_preferences import UiPreferencesService
from vibesensor.shared.ports import SettingsSnapshotPersistence
from vibesensor.shared.time_utils import utc_now_iso

__all__ = ["PersistedSettingsServices", "build_settings_services", "write_raw_settings_snapshot"]


@dataclass(slots=True)
class PersistedSettingsServices:
    coordinator: SettingsPersistenceCoordinator
    car_settings: CarSettingsService
    analysis_settings: ActiveCarAnalysisSettingsService
    sensor_settings: SensorSettingsService
    speed_source_settings: PersistedSpeedSourceSettingsService
    ui_preferences: UiPreferencesService
    settings_reader: SettingsDerivationService


def build_settings_services(
    db: SettingsSnapshotPersistence | None = None,
) -> PersistedSettingsServices:
    """Build the focused persisted settings services used by production wiring."""

    coordinator = SettingsPersistenceCoordinator(db=db)
    car_settings = CarSettingsService(
        lock=coordinator.lock,
        state=coordinator.car_state,
        update_with_rollback=coordinator.update_with_rollback,
    )
    analysis_settings = ActiveCarAnalysisSettingsService(
        active_car_aspects=car_settings.active_car_aspects,
        update_active_car_aspects=car_settings.update_active_car_aspects,
    )
    sensor_settings = SensorSettingsService(
        lock=coordinator.lock,
        state=coordinator.sensor_state,
        update_with_rollback=coordinator.update_with_rollback,
    )
    speed_source_settings = PersistedSpeedSourceSettingsService(
        lock=coordinator.lock,
        state=coordinator.speed_source_state,
        update_with_rollback=coordinator.update_with_rollback,
    )
    ui_preferences = UiPreferencesService(
        lock=coordinator.lock,
        state=coordinator.ui_preferences_state,
        update_with_rollback=coordinator.update_with_rollback,
    )
    settings_reader = SettingsDerivationService(
        active_car_aspects=car_settings.active_car_aspects,
        active_car_snapshot=car_settings.active_car_snapshot,
    )
    return PersistedSettingsServices(
        coordinator=coordinator,
        car_settings=car_settings,
        analysis_settings=analysis_settings,
        sensor_settings=sensor_settings,
        speed_source_settings=speed_source_settings,
        ui_preferences=ui_preferences,
        settings_reader=settings_reader,
    )


def write_raw_settings_snapshot(db: Any, value_json: str) -> None:
    """Write raw JSON into the settings snapshot table for load-path tests."""

    with db._cursor() as cur:
        cur.execute(
            "INSERT INTO settings_snapshot (id, value_json, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET value_json = excluded.value_json, "
            "updated_at = excluded.updated_at",
            (value_json, utc_now_iso()),
        )
