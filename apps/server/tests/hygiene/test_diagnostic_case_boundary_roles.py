"""Guard diagnostic-case boundary ownership versus domain and use-case factories."""

from __future__ import annotations

import vibesensor.shared.boundaries.analysis_payloads.reconstruction.case as diagnostic_case
import vibesensor.shared.boundaries.runs.projection as run_metadata_projection
from vibesensor.domain import Car, SpeedProfile, Symptom
from vibesensor.use_cases.diagnostics import _analysis_result_builder, run_data_preparation


def test_diagnostic_case_boundary_does_not_expose_domain_factories() -> None:
    assert callable(SpeedProfile.from_stats)
    assert not hasattr(Car, "from_metadata")
    assert not hasattr(Symptom, "from_metadata")
    assert not hasattr(diagnostic_case, "car_from_metadata")
    assert not hasattr(diagnostic_case, "symptom_from_metadata")
    assert callable(run_metadata_projection.car_from_run_metadata)
    assert callable(run_metadata_projection.symptom_from_run_metadata)
    assert not hasattr(diagnostic_case, "speed_profile_from_stats")
    assert not hasattr(diagnostic_case, "case_context_from_metadata")
    assert not hasattr(diagnostic_case, "project_analysis_summary")
    assert not hasattr(diagnostic_case, "run_suitability_payload")
    assert not hasattr(diagnostic_case, "run_suitability_from_payload")
    assert not hasattr(diagnostic_case, "test_run_from_summary")
    assert not hasattr(diagnostic_case, "_enrich_findings")


def test_diagnostics_use_cases_do_not_reexport_boundary_factories() -> None:
    assert not hasattr(run_data_preparation, "speed_profile_from_stats")
    assert not hasattr(_analysis_result_builder, "case_context_from_metadata")
