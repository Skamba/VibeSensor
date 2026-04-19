"""Contract bridge tests: Analysis → Report boundary.

These tests validate that the output of ``summarize_run_data()`` can be
prepared and accepted by ``build_report_document()``. They are fast (<5 s),
deterministic, and run in standard CI so schema drift between the two
subsystems is caught early.
"""

from __future__ import annotations

import pytest
from test_support import (
    ALL_WHEEL_SENSORS,
    make_fault_samples,
    make_noise_samples,
    standard_metadata,
)

from vibesensor.adapters.analysis_summary import (
    analysis_result_to_summary,
    summarize_run_data,
)
from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.shared.boundaries.reporting.document import ReportDocument
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.use_cases.diagnostics._run_input import build_diagnostics_run_input
from vibesensor.use_cases.diagnostics.run_analysis import RunAnalysis
from vibesensor.use_cases.history.report_document import (
    build_report_document,
    resolve_primary_report_candidate,
)

pytestmark = pytest.mark.smoke


def _make_small_dataset() -> tuple[dict, list[dict]]:
    """Return a minimal (metadata, samples) pair with a detectable fault."""
    meta = standard_metadata(language="en")
    samples: list[dict] = []
    samples.extend(make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=15, speed_kmh=60.0))
    samples.extend(
        make_fault_samples(
            fault_sensor="front-left",
            sensors=ALL_WHEEL_SENSORS,
            speed_kmh=80.0,
            n_samples=20,
        )
    )
    return meta, samples


def _make_steady_speed_fault_dataset() -> tuple[dict, list[dict]]:
    """Return a steady-speed dataset with a clear wheel fault."""
    meta = standard_metadata(language="en")
    samples = make_fault_samples(
        fault_sensor="front-left",
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=80.0,
        n_samples=20,
        fault_amp=0.07,
        fault_vib_db=28.0,
        noise_vib_db=8.0,
    )
    return meta, samples


def _report_data_from_samples(
    meta: dict,
    samples: list[dict],
    *,
    lang: str,
) -> ReportDocument:
    summary = summarize_run_data(meta, samples, lang=lang)
    return build_report_document(prepare_report_input(summary))


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


def test_analysis_output_accepted_by_report_mapper():
    """summarize_run_data() output must prepare and map cleanly."""
    meta, samples = _make_small_dataset()
    summary = summarize_run_data(meta, samples, lang="en")
    prepared = prepare_report_input(summary)
    report_data = build_report_document(prepared)

    assert prepared.domain_test_run is not None
    assert isinstance(report_data, ReportDocument)
    assert report_data.run_id == summary["run_id"] == prepared.report_facts.run.run_id
    assert report_data.sensor_count == summary["sensor_count_used"]
    assert report_data.sensor_locations == summary["sensor_locations"]
    assert report_data.top_causes

    domain_top_cause = prepared.domain_test_run.effective_top_causes()[0]
    report_top_cause = report_data.top_causes[0]
    assert report_top_cause.suspected_source == str(domain_top_cause.suspected_source)
    assert report_top_cause.strongest_location == domain_top_cause.strongest_location
    assert report_top_cause.order == domain_top_cause.order
    assert report_top_cause.effective_confidence == pytest.approx(
        domain_top_cause.effective_confidence,
    )


def test_report_data_has_populated_fields():
    """Key report fields must be non-empty after mapping real analysis output."""
    meta, samples = _make_small_dataset()
    report_data = _report_data_from_samples(meta, samples, lang="en")

    # Structural: the report must have a title and language
    assert report_data.title
    assert report_data.lang == "en"

    # Content: sensor information propagated
    assert report_data.sensor_count > 0
    assert len(report_data.sensor_locations) > 0

    # Diagnostic output: observed signature populated
    assert report_data.observed.certainty_label


def test_analysis_without_fault_maps_cleanly():
    """A run with only road-noise (no fault) must still map without errors."""
    meta = standard_metadata(language="en")
    samples = make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30, speed_kmh=60.0)
    report_data = _report_data_from_samples(meta, samples, lang="en")

    assert isinstance(report_data, ReportDocument)
    assert report_data.lang == "en"


def test_multilingual_mapping():
    """Analysis + report mapping must work for non-English languages."""
    meta = standard_metadata(language="nl")
    samples = make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=20, speed_kmh=60.0)
    report_data = _report_data_from_samples(meta, samples, lang="nl")

    assert isinstance(report_data, ReportDocument)
    assert report_data.lang == "nl"


def test_report_certainty_uses_confidence_assessment_reason() -> None:
    """Report certainty reason comes from ConfidenceAssessment on the domain finding."""
    meta, samples = _make_steady_speed_fault_dataset()
    analysis = RunAnalysis(
        build_diagnostics_run_input(
            run_metadata_from_mapping(meta),
            sensor_frames_from_mappings(samples),
            file_name="ca-reason-proof",
        ),
        lang="en",
        file_name="ca-reason-proof",
    )
    result = analysis.summarize()
    summary = analysis_result_to_summary(result)

    prepared = prepare_report_input(summary)
    assert prepared.domain_test_run is not None
    assert prepared.report_facts is not None
    assert prepared.domain_test_run.speed_profile is not None

    primary = resolve_primary_report_candidate(
        aggregate=prepared.domain_test_run,
        facts=prepared.report_facts.decision.primary_candidate,
        tr=lambda key, **_kw: key,
        lang="en",
    )

    # Reason must come from ConfidenceAssessment, not from the deleted certainty_label()
    effective = prepared.domain_test_run.effective_top_causes()
    domain_primary = effective[0] if effective else prepared.domain_test_run.primary_finding
    assert domain_primary is not None
    assert domain_primary.confidence_assessment is not None
    assert primary.certainty_reason == domain_primary.confidence_assessment.reason
