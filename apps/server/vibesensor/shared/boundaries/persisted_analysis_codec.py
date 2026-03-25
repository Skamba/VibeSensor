"""Boundary codec between AnalysisSummary payloads and PersistedAnalysis objects."""

from __future__ import annotations

from typing import cast

from vibesensor.shared.types.history_analysis_contracts import AnalysisSummary
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis


def persisted_analysis_from_summary(summary: AnalysisSummary) -> PersistedAnalysis:
    return PersistedAnalysis.from_json_object(cast(JsonObject, summary))


def persisted_analysis_to_summary(model: PersistedAnalysis) -> AnalysisSummary:
    return cast(AnalysisSummary, model.to_json_object())
