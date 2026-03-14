"""Contract bridge tests: Analysis → Report boundary.

These tests validate that the output of ``summarize_run_data()`` is a valid
input to ``map_summary()``.  They are fast (<5 s), deterministic, and run in
standard CI so that schema drift between the two subsystems is caught early.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from test_support import (
    ALL_WHEEL_SENSORS,
    make_fault_samples,
    make_noise_samples,
    standard_metadata,
)

from vibesensor.analysis import AnalysisSummary, RunAnalysis, summarize_run_data
from vibesensor.report.mapping import (
    map_summary,
    prepare_report_mapping_context,
    resolve_primary_report_candidate,
)
from vibesensor.report.report_data import ReportTemplateData


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


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


def test_analysis_output_accepted_by_report_mapper():
    """summarize_run_data() output must be accepted by map_summary()."""
    meta, samples = _make_small_dataset()
    summary: AnalysisSummary = summarize_run_data(meta, samples, lang="en")

    report_data = map_summary(summary)

    assert isinstance(report_data, ReportTemplateData)


def test_report_data_has_populated_fields():
    """Key report fields must be non-empty after mapping real analysis output."""
    meta, samples = _make_small_dataset()
    summary = summarize_run_data(meta, samples, lang="en")
    report_data = map_summary(summary)

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
    summary = summarize_run_data(meta, samples, lang="en")

    report_data = map_summary(summary)

    assert isinstance(report_data, ReportTemplateData)
    assert report_data.lang == "en"


def test_multilingual_mapping():
    """Analysis + report mapping must work for non-English languages."""
    meta = standard_metadata(language="nl")
    samples = make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=20, speed_kmh=60.0)
    summary = summarize_run_data(meta, samples, lang="nl")

    report_data = map_summary(summary)

    assert isinstance(report_data, ReportTemplateData)
    assert report_data.lang == "nl"


def test_report_certainty_smoke_uses_speed_profile_over_raw_speed_stats() -> None:
    """Report certainty should follow the live aggregate speed profile, not raw speed_stats."""
    meta, samples = _make_steady_speed_fault_dataset()
    analysis = RunAnalysis(meta, samples, lang="en", file_name="steady-speed-proof")
    result = analysis.summarize()
    summary = result.summary

    assert analysis.test_run is not None
    assert analysis.test_run.speed_profile is not None
    assert analysis.test_run.speed_profile.steady_speed is True

    stripped_findings = tuple(
        replace(finding, confidence_assessment=None)
        for finding in analysis.test_run.findings
    )
    stripped_top_causes = tuple(
        replace(finding, confidence_assessment=None)
        for finding in analysis.test_run.top_causes
    )
    stripped_aggregate = replace(
        analysis.test_run,
        findings=stripped_findings,
        top_causes=stripped_top_causes,
    )

    corrupted_summary = deepcopy(summary)
    corrupted_summary["speed_stats"]["steady_speed"] = False

    context = prepare_report_mapping_context(corrupted_summary)
    context = replace(context, domain_aggregate=stripped_aggregate)

    primary = resolve_primary_report_candidate(
        corrupted_summary,
        context=context,
        tr=lambda key, **_kw: key,
        lang="en",
    )

    assert context.speed_stats["steady_speed"] is False
    assert primary.certainty_reason == "Limited speed variation reduces tracking confidence"
