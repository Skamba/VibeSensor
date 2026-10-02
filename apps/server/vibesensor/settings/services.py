"""Build the persisted settings services around one shared coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.settings.analysis_settings import ActiveCarAnalysisSettingsService
from vibesensor.settings.car_settings import CarSettingsService
from vibesensor.settings.sensor_settings import SensorSettingsService
from vibesensor.settings.settings_derivation import SettingsDerivationService
from vibesensor.settings.settings_persistence import SettingsPersistenceCoordinator
from vibesensor.settings.speed_source_runtime import (
    SpeedSourceRuntimeApplier,
    SpeedSourceSettingsService,
)
from vibesensor.settings.speed_source_settings import PersistedSpeedSourceSettingsService
from vibesensor.settings.ui_preferences import UiPreferencesService

if TYPE_CHECKING:
    from vibesensor.history.history_db import HistoryDB
    from vibesensor.speed.source_coordinator import SpeedSourceControlService

__all__ = ["SettingsServices", "build_settings_services"]


@dataclass(slots=True)
class SettingsServices:
    """The settings services; all share the coordinator's lock and rollback."""

    coordinator: SettingsPersistenceCoordinator
    car_settings: CarSettingsService
    analysis_settings: ActiveCarAnalysisSettingsService
    sensor_settings: SensorSettingsService
    speed_source_settings: PersistedSpeedSourceSettingsService
    ui_preferences: UiPreferencesService
    settings_reader: SettingsDerivationService
    speed_source_service: SpeedSourceSettingsService


def build_settings_services(
    db: HistoryDB | None = None,
    speed_control: SpeedSourceControlService | None = None,
) -> SettingsServices:
    """Load the persisted settings snapshot from *db* and build every settings service."""
    coordinator = SettingsPersistenceCoordinator(db=db)
    car_settings = CarSettingsService(
        lock=coordinator.lock,
        state=coordinator.car_state,
        update_with_rollback=coordinator.update_with_rollback,
    )
    speed_source_settings = PersistedSpeedSourceSettingsService(
        lock=coordinator.lock,
        state=coordinator.speed_source_state,
        update_with_rollback=coordinator.update_with_rollback,
    )
    return SettingsServices(
        coordinator=coordinator,
        car_settings=car_settings,
        analysis_settings=ActiveCarAnalysisSettingsService(
            active_car_aspects=car_settings.active_car_aspects,
            update_active_car_aspects=car_settings.update_active_car_aspects,
        ),
        sensor_settings=SensorSettingsService(
            lock=coordinator.lock,
            state=coordinator.sensor_state,
            update_with_rollback=coordinator.update_with_rollback,
        ),
        speed_source_settings=speed_source_settings,
        ui_preferences=UiPreferencesService(
            lock=coordinator.lock,
            state=coordinator.ui_preferences_state,
            update_with_rollback=coordinator.update_with_rollback,
        ),
        settings_reader=SettingsDerivationService(
            active_car_aspects=car_settings.active_car_aspects,
            active_car_snapshot=car_settings.active_car_snapshot,
        ),
        speed_source_service=SpeedSourceSettingsService(
            settings_store=speed_source_settings,
            runtime_applier=SpeedSourceRuntimeApplier(speed_control=speed_control),
        ),
    )
