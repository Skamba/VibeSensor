"""Invariant: every Finding in a TestRun must have a non-None ConfidenceAssessment."""

from __future__ import annotations

from typing import Any

from test_support import standard_metadata
from test_support.scenario_ground_truth import ALL_SENSORS, fault_phase

from vibesensor.adapters.analysis_summary import analysis_result_to_summary
from vibesensor.shared.boundaries.run_metadata_codec import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frame_decoder import sensor_frames_from_mappings
from vibesensor.shared.boundaries.test_run_reconstruction import (
    test_run_from_summary as _decode_test_run,
)
from vibesensor.use_cases.diagnostics._run_input import build_diagnostics_run_input
from vibesensor.use_cases.diagnostics.run_analysis import RunAnalysis


def _assert_all_findings_have_assessment(findings: tuple[Any, ...]) -> None:
    missing = [
        f.finding_id or f.suspected_source for f in findings if f.confidence_assessment is None
    ]
    assert not missing, f"Findings without ConfidenceAssessment: {missing}"


def _wheel_fault_result(file_name: str):
    return RunAnalysis(
        build_diagnostics_run_input(
            run_metadata_from_mapping(standard_metadata()),
            sensor_frames_from_mappings(
                fault_phase(
                    speed_kmh=80.0,
                    duration_s=20.0,
                    fault_sensor="front-right",
                    sensors=ALL_SENSORS,
                ),
            ),
            file_name=file_name,
        ),
        lang="en",
        file_name=file_name,
    ).summarize()


class TestLivePipelineConfidenceInvariant:
    """All findings produced by live analysis must carry ConfidenceAssessment."""

    def test_wheel_fault_all_findings_assessed(self) -> None:
        result = _wheel_fault_result("invariant-wheel")
        test_run = result.test_run

        assert test_run is not None
        assert len(test_run.findings) > 0
        _assert_all_findings_have_assessment(test_run.findings)

    def test_top_causes_subset_of_enriched_findings(self) -> None:
        result = _wheel_fault_result("invariant-subset")
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
        result = _wheel_fault_result("invariant-decode")
        summary = analysis_result_to_summary(result)

        # Decode through the boundary (simulates historical data load)
        decoded_run = _decode_test_run(summary)

        assert len(decoded_run.findings) > 0
        _assert_all_findings_have_assessment(decoded_run.findings)

    def test_decoded_top_causes_assessed(self) -> None:
        result = _wheel_fault_result("invariant-decode-tc")
        summary = analysis_result_to_summary(result)

        decoded_run = _decode_test_run(summary)

        assert len(decoded_run.top_causes) > 0
        _assert_all_findings_have_assessment(decoded_run.top_causes)
