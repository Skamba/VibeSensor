"""Shared builders for focused persisted settings service bundles in tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from vibesensor.app.container import build_settings_service_bundle
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

    services = build_settings_service_bundle(
        snapshot_repository=db,
        speed_control=None,
    )
    return PersistedSettingsServices(
        coordinator=services.coordinator,
        car_settings=services.car_settings,
        analysis_settings=services.analysis_settings,
        sensor_settings=services.sensor_metadata_store,
        speed_source_settings=services.speed_source_settings,
        ui_preferences=services.ui_preferences,
        settings_reader=services.settings_reader,
    )


def write_raw_settings_snapshot(db: Any, value_json: str) -> None:
    """Write raw JSON into the settings snapshot table for load-path tests."""

    async def _run() -> None:
        async with db._cursor() as cur:
            await cur.execute(
                "INSERT INTO settings_snapshot (id, value_json, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET value_json = excluded.value_json, "
                "updated_at = excluded.updated_at",
                (value_json, utc_now_iso()),
            )

    asyncio.run(_run())
