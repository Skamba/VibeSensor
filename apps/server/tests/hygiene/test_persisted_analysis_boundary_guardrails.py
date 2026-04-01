"""Guardrails keeping persisted analysis separate from outward summary contracts."""

from __future__ import annotations

from vibesensor.shared.types.history_analysis_contracts import AnalysisSummaryResponse
from vibesensor.shared.types.persisted_analysis_contracts import PersistedAnalysisPayload


def test_persisted_analysis_payload_has_distinct_owner_from_summary_contract() -> None:
    assert PersistedAnalysisPayload is not AnalysisSummaryResponse
