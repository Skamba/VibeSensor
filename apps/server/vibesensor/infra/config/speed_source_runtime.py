"""Explicit runtime orchestration for persisted speed-source settings."""

from __future__ import annotations

from vibesensor.shared.ports import SpeedSourceSettingsStore, SpeedSourceSync
from vibesensor.shared.types.speed_source_config import (
    SpeedSourceConfig,
    SpeedSourcePayload,
    SpeedSourceUpdatePayload,
)

__all__ = [
    "SpeedSourceRuntimeApplier",
    "SpeedSourceSettingsService",
]


class SpeedSourceRuntimeApplier:
    """Push a canonical speed-source config into long-lived runtime monitors."""

    __slots__ = ("_speed_control",)

    def __init__(self, *, speed_control: SpeedSourceSync | None) -> None:
        self._speed_control = speed_control

    def apply(self, config: SpeedSourceConfig) -> None:
        if self._speed_control is None:
            return
        self._speed_control.apply_speed_source_settings(
            effective_speed_kmh=config.manual_speed_kph,
            manual_source_selected=config.manual_source_selected,
            stale_timeout_s=config.stale_timeout_s,
            selected_source=config.speed_source,
            obd_device_mac=config.obd_device_mac,
            obd_device_name=config.obd_device_name,
        )


class SpeedSourceSettingsService:
    """Coordinate persisted speed-source updates with runtime application."""

    __slots__ = ("_settings_store", "_runtime_applier")

    def __init__(
        self,
        *,
        settings_store: SpeedSourceSettingsStore,
        runtime_applier: SpeedSourceRuntimeApplier,
    ) -> None:
        self._settings_store = settings_store
        self._runtime_applier = runtime_applier

    def get_speed_source(self) -> SpeedSourcePayload:
        return self._settings_store.get_speed_source()

    def update_speed_source(self, data: SpeedSourceUpdatePayload) -> SpeedSourcePayload:
        persisted = self._settings_store.persist_speed_source(
            self._settings_store.preview_speed_source_update(data),
        )
        self._runtime_applier.apply(persisted)
        return persisted.to_dict()

    def sync_all(self) -> None:
        self._runtime_applier.apply(self._settings_store.speed_source_config())
