"""Settings-reader port used by recording and history use-cases.

This protocol captures the narrow ``SettingsStore`` read surface currently
consumed by ``use_cases/run/`` and ``use_cases/history/``. Issue ``#814`` will
later consolidate these focused protocols into a shared ``ports.py`` module.
"""

from __future__ import annotations

from typing import Protocol

from vibesensor.domain import AnalysisSettingsSnapshot, CarSnapshot

__all__ = ["SettingsReader"]


class SettingsReader(Protocol):
    """Read-only settings access needed by recording and history flows."""

    def analysis_settings_snapshot(self) -> AnalysisSettingsSnapshot: ...

    def active_car_snapshot(self) -> CarSnapshot | None: ...
