"""Common settings-facing shared type aliases."""

from __future__ import annotations

from typing import Literal

__all__ = [
    "AnalysisSettingsPayload",
    "LanguageCode",
    "SpeedUnitCode",
]

type AnalysisSettingsPayload = dict[str, float]
type LanguageCode = Literal["en", "nl"]
type SpeedUnitCode = Literal["kmh", "mps"]
