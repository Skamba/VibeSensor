"""Invariant: every Finding in a TestRun must have a non-None ConfidenceAssessment."""

from __future__ import annotations

from typing import Any

from test_support import standard_metadata
from test_support.scenario_ground_truth import ALL_SENSORS, fault_phase

from vibesensor.use_cases.diagnostics import RunAnalysis
from vibesensor.shared.boundaries.diagnostic_case import (
    test_run_from_summary as _decode_test_run,
)


def _assert_all_findings_have_assessment(findings: tuple[Any, ...]) -> None:
    missing = [
        f.finding_id or f.suspected_source for f in findings if f.confidence_assessment is None
    ]
    assert not missing, f"Findings without ConfidenceAssessment: {missing}"


class TestLivePipelineConfidenceInvariant:
    """All findings produced by live analysis must carry ConfidenceAssessment."""

    def test_wheel_fault_all_findings_assessed(self) -> None:
        analysis = RunAnalysis(
            standard_metadata(),
            fault_phase(
                speed_kmh=80.0,
                duration_s=20.0,
                fault_sensor="front-right",
                sensors=ALL_SENSORS,
            ),
            lang="en",
            file_name="invariant-wheel",
        )
        result = analysis.summarize()
        test_run = result.test_run

        assert test_run is not None
        assert len(test_run.findings) > 0
        _assert_all_findings_have_assessment(test_run.findings)

    def test_top_causes_subset_of_enriched_findings(self) -> None:
        analysis = RunAnalysis(
            standard_metadata(),
            fault_phase(
                speed_kmh=80.0,
                duration_s=20.0,
                fault_sensor="front-right",
                sensors=ALL_SENSORS,
            ),
            lang="en",
            file_name="invariant-subset",
        )
        result = analysis.summarize()
        test_run = result.test_run

        assert test_run is not None
        # Top causes must be a subset of findings (same objects)
        finding_ids = {f.finding_id for f in test_run.findings if f.finding_id}
        for tc in test_run.top_causes:
            assert tc.finding_id in finding_ids
            assert tc.confidence_assessment is not None


class TestBoundaryDecoderConfidenceInvariant:
    """Findings decoded from historical summary payloads get synthesized assessment."""

    def test_decoded_findings_all_assessed(self) -> None:
        analysis = RunAnalysis(
            standard_metadata(),
            fault_phase(
                speed_kmh=80.0,
                duration_s=20.0,
                fault_sensor="front-right",
                sensors=ALL_SENSORS,
            ),
            lang="en",
            file_name="invariant-decode",
        )
        result = analysis.summarize()
        summary = result.summary

        # Decode through the boundary (simulates historical data load)
        decoded_run = _decode_test_run(summary)

        assert len(decoded_run.findings) > 0
        _assert_all_findings_have_assessment(decoded_run.findings)

    def test_decoded_top_causes_assessed(self) -> None:
        analysis = RunAnalysis(
            standard_metadata(),
            fault_phase(
                speed_kmh=80.0,
                duration_s=20.0,
                fault_sensor="front-right",
                sensors=ALL_SENSORS,
            ),
            lang="en",
            file_name="invariant-decode-tc",
        )
        result = analysis.summarize()
        summary = result.summary

        decoded_run = _decode_test_run(summary)

        assert len(decoded_run.top_causes) > 0
        _assert_all_findings_have_assessment(decoded_run.top_causes)
