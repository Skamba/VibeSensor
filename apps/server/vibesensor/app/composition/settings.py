from __future__ import annotations

from dataclasses import dataclass

from vibesensor.adapters.http.dependencies import (
    ObdAdminServiceProtocol,
    SettingsDeps,
    SettingsSpeedServiceProtocol,
)
from vibesensor.infra.config.analysis_settings import ActiveCarAnalysisSettingsService
from vibesensor.infra.config.car_settings import CarSettingsService
from vibesensor.infra.config.sensor_settings import SensorSettingsService
from vibesensor.infra.config.settings_derivation import SettingsDerivationService
from vibesensor.infra.config.settings_persistence import SettingsPersistenceCoordinator
from vibesensor.infra.config.speed_source_runtime import (
    SpeedSourceRuntimeApplier,
    SpeedSourceSettingsService,
)
from vibesensor.infra.config.speed_source_settings import PersistedSpeedSourceSettingsService
from vibesensor.infra.config.ui_preferences import UiPreferencesService
from vibesensor.shared.ports import (
    LanguageReader,
    SensorMetadataReader,
    SettingsReader,
    SettingsSnapshotPersistence,
    SpeedSourceSettingsReader,
    SpeedSourceSync,
)


@dataclass(frozen=True, slots=True)
class RuntimeSettingsDeps:
    """Focused settings readers needed by long-lived runtime collaborators."""

    settings_reader: SettingsReader
    speed_source_reader: SpeedSourceSettingsReader
    sensor_metadata_reader: SensorMetadataReader
    language_reader: LanguageReader


@dataclass(slots=True)
class SettingsServiceBundle:
    """Explicit settings wiring bundle for runtime and HTTP assembly."""

    coordinator: SettingsPersistenceCoordinator
    car_settings: CarSettingsService
    analysis_settings: ActiveCarAnalysisSettingsService
    sensor_metadata_store: SensorSettingsService
    speed_source_settings: PersistedSpeedSourceSettingsService
    ui_preferences: UiPreferencesService
    settings_reader: SettingsDerivationService
    speed_source_service: SpeedSourceSettingsService

    def runtime_deps(self) -> RuntimeSettingsDeps:
        """Return the focused runtime readers derived from this bundle."""

        return RuntimeSettingsDeps(
            settings_reader=self.settings_reader,
            speed_source_reader=self.speed_source_settings,
            sensor_metadata_reader=self.sensor_metadata_store,
            language_reader=self.ui_preferences,
        )

    def http_settings_deps(
        self,
        *,
        speed_status_service: SettingsSpeedServiceProtocol,
        obd_admin_service: ObdAdminServiceProtocol,
    ) -> SettingsDeps:
        """Return the focused HTTP settings dependency group."""

        return SettingsDeps(
            car_settings=self.car_settings,
            analysis_settings=self.analysis_settings,
            ui_preferences=self.ui_preferences,
            speed_source_service=self.speed_source_service,
            speed_status_service=speed_status_service,
            obd_admin_service=obd_admin_service,
        )


def build_settings_service_bundle(
    *,
    snapshot_repository: SettingsSnapshotPersistence | None,
    speed_control: SpeedSourceSync | None,
) -> SettingsServiceBundle:
    """Build the explicit settings bundle used by runtime and HTTP assembly."""

    coordinator = SettingsPersistenceCoordinator(db=snapshot_repository)
    car_settings = CarSettingsService(
        lock=coordinator.lock,
        state=coordinator.car_state,
        update_with_rollback=coordinator.update_with_rollback,
    )
    analysis_settings = ActiveCarAnalysisSettingsService(
        active_car_aspects=car_settings.active_car_aspects,
        update_active_car_aspects=car_settings.update_active_car_aspects,
    )
    sensor_metadata_store = SensorSettingsService(
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

    return SettingsServiceBundle(
        coordinator=coordinator,
        car_settings=car_settings,
        analysis_settings=analysis_settings,
        sensor_metadata_store=sensor_metadata_store,
        speed_source_settings=speed_source_settings,
        ui_preferences=ui_preferences,
        settings_reader=settings_reader,
        speed_source_service=SpeedSourceSettingsService(
            settings_store=speed_source_settings,
            runtime_applier=SpeedSourceRuntimeApplier(
                speed_control=speed_control,
            ),
        ),
    )
