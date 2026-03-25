from __future__ import annotations

from vibesensor.domain import Car, SpeedProfile, Symptom
from vibesensor.shared.boundaries import diagnostic_case
from vibesensor.use_cases.diagnostics import _summary_result, run_data_preparation


def test_diagnostic_case_boundary_does_not_expose_domain_factories() -> None:
    assert callable(SpeedProfile.from_stats)
    assert callable(Car.from_metadata)
    assert callable(Symptom.from_metadata)
    assert not hasattr(diagnostic_case, "speed_profile_from_stats")
    assert not hasattr(diagnostic_case, "case_context_from_metadata")
    assert not hasattr(diagnostic_case, "project_analysis_summary")
    assert not hasattr(diagnostic_case, "run_suitability_payload")
    assert not hasattr(diagnostic_case, "run_suitability_from_payload")
    assert not hasattr(diagnostic_case, "test_run_from_summary")
    assert not hasattr(diagnostic_case, "_enrich_findings")


def test_diagnostics_use_cases_do_not_reexport_boundary_factories() -> None:
    assert not hasattr(run_data_preparation, "speed_profile_from_stats")
    assert not hasattr(_summary_result, "case_context_from_metadata")
