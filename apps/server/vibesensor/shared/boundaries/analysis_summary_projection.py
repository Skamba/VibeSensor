"""Project persisted analysis summaries back into canonical boundary payload form."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from vibesensor.domain.test_run import TestRun
from vibesensor.shared.boundaries.diagnostic_case import test_run_from_summary
from vibesensor.shared.boundaries.finding import (
    _has_structured_step_content,
    finding_payload_from_domain,
    step_payloads_from_plan,
)
from vibesensor.shared.boundaries.run_suitability import run_suitability_payload
from vibesensor.shared.boundaries.vibration_origin import origin_payload_from_finding
from vibesensor.shared.types.json_types import JsonObject


def project_analysis_summary(analysis: JsonObject) -> tuple[JsonObject, TestRun]:
    """Reconstruct and re-serialize analysis through the canonical domain boundary."""
    test_run = test_run_from_summary(analysis)
    projected: dict[str, object] = dict(analysis)
    projected["findings"] = [finding_payload_from_domain(f) for f in test_run.findings]
    projected["top_causes"] = [
        finding_payload_from_domain(f) for f in test_run.effective_top_causes()
    ]
    primary = test_run.primary_finding
    origin_fb = analysis.get("most_likely_origin")
    fb_payload = dict(origin_fb) if isinstance(origin_fb, Mapping) else {}
    if primary is None:
        projected["most_likely_origin"] = fb_payload
    else:
        projected["most_likely_origin"] = origin_payload_from_finding(primary)
    if not _has_structured_step_content(analysis.get("test_plan")):
        projected["test_plan"] = step_payloads_from_plan(test_run.test_plan)
    projected["run_suitability"] = run_suitability_payload(test_run.suitability)
    return cast(JsonObject, projected), test_run
