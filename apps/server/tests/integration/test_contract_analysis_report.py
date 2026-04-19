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


def _summarize_and_prepare_report(
    meta: dict,
    samples: list[dict],
    *,
    lang: str,
) -> tuple[dict, object, ReportDocument]:
    summary = summarize_run_data(meta, samples, lang=lang)
    prepared = prepare_report_input(summary)
    return summary, prepared, build_report_document(prepared)


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("meta", "samples", "lang", "expect_top_cause_mapping"),
    [
        pytest.param(*_make_small_dataset(), "en", True, id="fault-en"),
        pytest.param(
            standard_metadata(language="en"),
            make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30, speed_kmh=60.0),
            "en",
            False,
            id="noise-en",
        ),
        pytest.param(
            standard_metadata(language="nl"),
            make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=20, speed_kmh=60.0),
            "nl",
            False,
            id="noise-nl",
        ),
    ],
)
def test_analysis_to_report_bridge_scenarios(
    meta: dict,
    samples: list[dict],
    lang: str,
    expect_top_cause_mapping: bool,
) -> None:
    """Analysis output should prepare and map cleanly across bridge scenarios."""
    summary, prepared, report_data = _summarize_and_prepare_report(
        meta,
        samples,
        lang=lang,
    )

    assert prepared.domain_test_run is not None
    assert isinstance(report_data, ReportDocument)
    assert report_data.run_id == summary["run_id"] == prepared.report_facts.run.run_id
    assert report_data.title
    assert report_data.lang == lang
    assert report_data.sensor_count == summary["sensor_count_used"]
    assert report_data.sensor_locations == summary["sensor_locations"]
    assert report_data.observed.certainty_label

    if not expect_top_cause_mapping:
        return

    assert report_data.top_causes
    domain_top_cause = prepared.domain_test_run.effective_top_causes()[0]
    report_top_cause = report_data.top_causes[0]
    assert report_top_cause.suspected_source == str(domain_top_cause.suspected_source)
    assert report_top_cause.strongest_location == domain_top_cause.strongest_location
    assert report_top_cause.order == domain_top_cause.order
    assert report_top_cause.effective_confidence == pytest.approx(
        domain_top_cause.effective_confidence,
    )


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
