"""Stateless settings applicators for car and speed-source configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..analysis_settings import AnalysisSettingsStore
    from ..gps_speed import GPSSpeedMonitor
    from ..settings_store import SettingsStore


def apply_car_settings(
    settings_store: SettingsStore,
    analysis_settings: AnalysisSettingsStore,
) -> None:
    """Push active car aspects into the shared AnalysisSettingsStore."""
    aspects = settings_store.active_car_aspects()
    if aspects:
        analysis_settings.update(aspects)


def apply_speed_source_settings(
    settings_store: SettingsStore,
    gps_monitor: GPSSpeedMonitor,
) -> None:
    """Push speed-source settings into GPSSpeedMonitor."""
    ss = settings_store.get_speed_source()
    gps_monitor.set_manual_source_selected(ss["speedSource"] == "manual")
    if ss["manualSpeedKph"] is not None:
        gps_monitor.set_speed_override_kmh(ss["manualSpeedKph"])
    else:
        gps_monitor.set_speed_override_kmh(None)
    gps_monitor.set_fallback_settings(
        stale_timeout_s=ss.get("staleTimeoutS"),
        fallback_mode=ss.get("fallbackMode"),
    )
