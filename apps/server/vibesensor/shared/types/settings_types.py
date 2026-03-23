"""Common settings-facing shared type aliases."""

from __future__ import annotations

from typing import Literal, TypeAlias

__all__ = [
    "AnalysisSettingsPayload",
    "LanguageCode",
    "SpeedUnitCode",
]

AnalysisSettingsPayload: TypeAlias = dict[str, float]
LanguageCode: TypeAlias = Literal["en", "nl"]
SpeedUnitCode: TypeAlias = Literal["kmh", "mps"]
