"""Contract bridge tests: Analysis → Report boundary.

These tests validate that the output of ``summarize_run_data()`` is a valid
input to ``map_summary()``.  They are fast (<5 s), deterministic, and run in
standard CI so that schema drift between the two subsystems is caught early.
"""

from __future__ import annotations

from test_support import (
    ALL_WHEEL_SENSORS,
    make_fault_samples,
    make_noise_samples,
    standard_metadata,
)

from vibesensor.analysis import SummaryData, map_summary, summarize_run_data
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


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


def test_analysis_output_accepted_by_report_mapper():
    """summarize_run_data() output must be accepted by map_summary()."""
    meta, samples = _make_small_dataset()
    summary: SummaryData = summarize_run_data(meta, samples, lang="en")

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
