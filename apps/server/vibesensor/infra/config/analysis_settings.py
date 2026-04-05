"""Focused analysis-settings service backed by the active car profile."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.domain import AnalysisSettingsSnapshot
from vibesensor.infra.config.settings_derivation import analysis_settings_snapshot_from_aspects
from vibesensor.shared.types.settings_types import AnalysisSettingsPayload

__all__ = ["ActiveCarAnalysisSettingsService"]


class ActiveCarAnalysisSettingsService:
    """Expose only the active-car analysis settings behavior needed by callers."""

    __slots__ = ("_active_car_aspects", "_update_active_car_aspects")

    def __init__(
        self,
        *,
        active_car_aspects: Callable[[], AnalysisSettingsPayload | None],
        update_active_car_aspects: Callable[[AnalysisSettingsPayload], AnalysisSettingsPayload],
    ) -> None:
        self._active_car_aspects = active_car_aspects
        self._update_active_car_aspects = update_active_car_aspects

    def analysis_settings_snapshot(self) -> AnalysisSettingsSnapshot:
        return analysis_settings_snapshot_from_aspects(self._active_car_aspects())

    def update_active_car_aspects(
        self,
        aspects: AnalysisSettingsPayload,
    ) -> AnalysisSettingsPayload:
        return self._update_active_car_aspects(aspects)
