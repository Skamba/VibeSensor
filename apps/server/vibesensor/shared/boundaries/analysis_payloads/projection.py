"""Project summary and persisted-analysis payloads back into canonical response form."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from vibesensor.domain.test_run import TestRun
from vibesensor.shared.boundaries.finding import finding_payload_from_domain
from vibesensor.shared.boundaries.run_suitability import run_suitability_payload
from vibesensor.shared.boundaries.test_plan_projection import (
    _has_structured_step_content,
    step_payloads_from_plan,
)
from vibesensor.shared.boundaries.vibration_origin import origin_payload_from_finding
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis

from .reconstruction import test_run_from_persisted_analysis, test_run_from_summary

__all__ = ["project_analysis_summary", "project_persisted_analysis"]


def _project_analysis_payload(
    analysis: Mapping[str, object],
    *,
    test_run: TestRun,
) -> JsonObject:
    projected: dict[str, object] = dict(analysis)
    projected["findings"] = [finding_payload_from_domain(f) for f in test_run.findings]
    projected["top_causes"] = [
        finding_payload_from_domain(f) for f in test_run.effective_top_causes()
    ]
    primary = test_run.primary_finding
    projected["most_likely_origin"] = (
        origin_payload_from_finding(primary) if primary is not None else {}
    )
    if not _has_structured_step_content(analysis.get("test_plan")):
        projected["test_plan"] = step_payloads_from_plan(test_run.test_plan)
    projected["run_suitability"] = run_suitability_payload(test_run.suitability)
    return cast(JsonObject, projected)


def project_analysis_summary(analysis: JsonObject) -> tuple[JsonObject, TestRun]:
    """Reconstruct and re-serialize an outward analysis summary."""
    test_run = test_run_from_summary(analysis)
    return _project_analysis_payload(analysis, test_run=test_run), test_run


def project_persisted_analysis(
    analysis: PersistedAnalysis,
) -> tuple[JsonObject, TestRun]:
    """Reconstruct and re-serialize storage-owned persisted analysis."""
    payload = analysis.to_json_object()
    test_run = test_run_from_persisted_analysis(analysis)
    return _project_analysis_payload(payload, test_run=test_run), test_run
