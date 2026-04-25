"""Derived current-settings readers built from persisted settings state."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from vibesensor.domain import AnalysisSettingsSnapshot, CarSnapshot
from vibesensor.shared.analysis_settings_schema import sanitize_analysis_settings
from vibesensor.shared.boundaries.codecs import analysis_settings_snapshot_from_mapping
from vibesensor.shared.ports import SettingsReader

__all__ = [
    "SettingsDerivationService",
    "analysis_settings_snapshot_from_aspects",
]


def analysis_settings_snapshot_from_aspects(
    aspects: Mapping[str, object] | None,
) -> AnalysisSettingsSnapshot:
    """Build the current typed analysis snapshot from active-car aspects."""
    values: dict[str, object] = dict(AnalysisSettingsSnapshot.DEFAULTS)
    if aspects:
        values.update(sanitize_analysis_settings(aspects))
    return analysis_settings_snapshot_from_mapping(values)


class SettingsDerivationService(SettingsReader):
    """Read-only current-settings view for recorder/history/runtime consumers."""

    __slots__ = ("_active_car_aspects", "_active_car_snapshot")

    def __init__(
        self,
        *,
        active_car_aspects: Callable[[], Mapping[str, object] | None],
        active_car_snapshot: Callable[[], CarSnapshot | None],
    ) -> None:
        self._active_car_aspects = active_car_aspects
        self._active_car_snapshot = active_car_snapshot

    def analysis_settings_snapshot(self) -> AnalysisSettingsSnapshot:
        return analysis_settings_snapshot_from_aspects(self._active_car_aspects())

    def active_car_snapshot(self) -> CarSnapshot | None:
        return self._active_car_snapshot()
