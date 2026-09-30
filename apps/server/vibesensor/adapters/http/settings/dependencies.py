"""Focused dependency groups for bounded-context settings micro-routers."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.adapters.http.dependencies import (
    ObdAdminServiceProtocol,
    SettingsSpeedServiceProtocol,
    SpeedSourceSettingsServiceProtocol,
)
from vibesensor.shared.ports import (
    AnalysisSettingsStore,
    CarSettingsStore,
    UiPreferencesStore,
)

__all__ = [
    "AnalysisSettingsRouteDeps",
    "CarSettingsRouteDeps",
    "ObdAdminRouteDeps",
    "SpeedSourceRouteDeps",
    "UiPreferencesRouteDeps",
]


@dataclass(frozen=True, slots=True)
class CarSettingsRouteDeps:
    car_settings: CarSettingsStore


@dataclass(frozen=True, slots=True)
class SpeedSourceRouteDeps:
    speed_source_service: SpeedSourceSettingsServiceProtocol
    speed_status_service: SettingsSpeedServiceProtocol


@dataclass(frozen=True, slots=True)
class ObdAdminRouteDeps:
    speed_source_service: SpeedSourceSettingsServiceProtocol
    speed_status_service: SettingsSpeedServiceProtocol
    obd_admin_service: ObdAdminServiceProtocol


@dataclass(frozen=True, slots=True)
class UiPreferencesRouteDeps:
    ui_preferences: UiPreferencesStore


@dataclass(frozen=True, slots=True)
class AnalysisSettingsRouteDeps:
    analysis_settings: AnalysisSettingsStore
