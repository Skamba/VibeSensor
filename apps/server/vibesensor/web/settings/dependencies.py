"""Focused dependency groups for bounded-context settings micro-routers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.web.dependencies import (
    ObdAdminServiceProtocol,
    SettingsSpeedServiceProtocol,
    SpeedSourceSettingsServiceProtocol,
)

if TYPE_CHECKING:
    from vibesensor.settings.analysis_settings import ActiveCarAnalysisSettingsService
    from vibesensor.settings.car_settings import CarSettingsService
    from vibesensor.settings.ui_preferences import UiPreferencesService

__all__ = [
    "AnalysisSettingsRouteDeps",
    "CarSettingsRouteDeps",
    "ObdAdminRouteDeps",
    "SpeedSourceRouteDeps",
    "UiPreferencesRouteDeps",
]


@dataclass(frozen=True, slots=True)
class CarSettingsRouteDeps:
    car_settings: CarSettingsService


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
    ui_preferences: UiPreferencesService


@dataclass(frozen=True, slots=True)
class AnalysisSettingsRouteDeps:
    analysis_settings: ActiveCarAnalysisSettingsService
