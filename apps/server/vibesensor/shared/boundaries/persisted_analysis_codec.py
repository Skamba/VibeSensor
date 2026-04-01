"""Explicit translation boundary between summary and persisted-analysis contracts."""

from __future__ import annotations

from typing import cast

from vibesensor.shared.types.history_analysis_contracts import AnalysisSummary
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis


def persisted_analysis_from_summary(summary: AnalysisSummary) -> PersistedAnalysis:
    """Translate a summary payload into the storage-owned persisted-analysis model."""
    return PersistedAnalysis.from_payload(summary)


def persisted_analysis_to_summary(model: PersistedAnalysis) -> AnalysisSummary:
    """Translate a persisted-analysis model back into the outward summary shape."""
    return cast(AnalysisSummary, cast(JsonObject, model.to_payload()))
