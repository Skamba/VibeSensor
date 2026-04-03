"""Tests for the enhanced ReportMappingContext with behavior methods."""

from __future__ import annotations

import pytest
from test_support.findings import make_finding_payload

from vibesensor.adapters.pdf import report_context
from vibesensor.adapters.pdf.mapping import (
    PrimaryCandidateContext,
    ReportMappingContext,
    prepare_report_input,
)
from vibesensor.domain import Finding, LocationIntensitySummary, TestRun
from vibesensor.domain.run_capture import RunCapture

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EMPTY_CAPTURE = RunCapture(run_id="test-run")


def _make_finding(**overrides: object) -> Finding:
    """Build a minimal domain Finding."""
    defaults: dict[str, object] = {
        "finding_id": "F001",
        "suspected_source": "wheel/tire",
        "confidence": 0.75,
        "strongest_location": "front_left",
    }
    defaults.update(overrides)
    return Finding(**defaults)


def _make_test_run(
    findings: tuple[Finding, ...] = (),
    top_causes: tuple[Finding, ...] = (),
) -> TestRun:
    """Build a TestRun with the given findings."""
    return TestRun(capture=_EMPTY_CAPTURE, findings=findings, top_causes=top_causes)


def _make_context(**overrides: object) -> ReportMappingContext:
    """Build a minimal ReportMappingContext with overrides."""
    if "domain_aggregate" not in overrides:
        overrides["domain_aggregate"] = _make_test_run()
    defaults: dict[str, object] = {
        "car_name": None,
        "car_type": None,
        "date_str": "2025-01-01 12:00:00 UTC",
        "origin": {
            "location": "unknown",
            "alternative_locations": [],
            "suspected_source": "unknown",
            "dominance_ratio": None,
            "weak_spatial_separation": True,
        },
        "origin_location": "",
        "sensor_locations_active": [],
        "duration_text": None,
        "start_time_utc": None,
        "end_time_utc": None,
        "sample_rate_hz": None,
        "tire_spec_text": None,
        "sample_count": 0,
        "sensor_model": None,
        "firmware_version": None,
    }
    defaults.update(overrides)
    return ReportMappingContext(**defaults)


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------


class TestTopReportCandidate:
    def test_returns_first_top_cause(self) -> None:
        f1 = _make_finding(finding_id="F001")
        f2 = _make_finding(finding_id="F002")
        aggregate = _make_test_run(findings=(f1, f2), top_causes=(f1,))
        context = _make_context(domain_aggregate=aggregate)
        result = context.top_report_candidate()
        assert result is not None
        assert result.finding_id == "F001"

    def test_falls_back_to_first_non_ref_finding(self) -> None:
        f1 = _make_finding(finding_id="F001")
        aggregate = _make_test_run(findings=(f1,))
        context = _make_context(domain_aggregate=aggregate)
        result = context.top_report_candidate()
        assert result is not None
        assert result.finding_id == "F001"

    def test_returns_none_when_empty(self) -> None:
        context = _make_context()
        assert context.top_report_candidate() is None


# ---------------------------------------------------------------------------
# Intensity queries
# ---------------------------------------------------------------------------


class TestHasSignificantLocationIntensity:
    def test_with_positive_intensity(self) -> None:
        context = _make_context()
        rows = [LocationIntensitySummary(location="front_left", p95_intensity_db=12.5)]
        assert context.has_significant_location_intensity(rows) is True

    def test_with_zero_intensity(self) -> None:
        context = _make_context()
        rows = [LocationIntensitySummary(location="front_left", p95_intensity_db=0.0)]
        assert context.has_significant_location_intensity(rows) is False

    def test_with_empty_rows(self) -> None:
        context = _make_context()
        assert context.has_significant_location_intensity([]) is False

    def test_with_missing_intensity_value(self) -> None:
        context = _make_context()
        rows = [LocationIntensitySummary(location="front_left")]
        assert context.has_significant_location_intensity(rows) is False


# ---------------------------------------------------------------------------
# Observed signature
# ---------------------------------------------------------------------------


class TestObservedSignature:
    def test_builds_from_primary(self) -> None:
        primary = PrimaryCandidateContext(
            primary_candidate=_make_finding(),
            primary_source="wheel/tire",
            primary_system="Wheel / Tire",
            primary_location="front_left",
            primary_speed="80-100 km/h",
            confidence=0.75,
            sensor_count=4,
            weak_spatial=False,
            has_reference_gaps=False,
            strength_db=22.0,
            strength_text="Moderate (22.0 dB)",
            strength_band_key="moderate",
            certainty_key="high",
            certainty_label_text="High",
            certainty_pct="75%",
            certainty_reason="Consistent order-tracking match",
            tier="C",
        )
        sig = report_context.observed_signature(primary)
        assert sig.primary_system == "Wheel / Tire"
        assert sig.strongest_location == "front_left"
        assert sig.speed_band == "80-100 km/h"
        assert sig.strength_label == "Moderate (22.0 dB)"
        assert sig.strength_peak_db == pytest.approx(22.0)
        assert sig.certainty_label == "High"
        assert sig.certainty_pct == "75%"


# ---------------------------------------------------------------------------
# Typed metadata fields
# ---------------------------------------------------------------------------


class TestTypedMetadata:
    def test_metadata_fields_are_typed(self) -> None:
        context = _make_context(
            duration_text="5m",
            start_time_utc="2025-01-01T00:00:00",
            end_time_utc="2025-01-01T00:05:00",
            sample_rate_hz="100",
            tire_spec_text="225/45R17",
            sample_count=500,
            sensor_model="ESP32",
            firmware_version="1.0.0",
        )
        assert context.duration_text == "5m"
        assert context.start_time_utc == "2025-01-01T00:00:00"
        assert context.end_time_utc == "2025-01-01T00:05:00"
        assert context.sample_rate_hz == "100"
        assert context.tire_spec_text == "225/45R17"
        assert context.sample_count == 500
        assert context.sensor_model == "ESP32"
        assert context.firmware_version == "1.0.0"


class TestPrepareReportMappingContext:
    def test_maps_renderer_and_report_fact_fields(self) -> None:
        finding = make_finding_payload(finding_id="F001")
        prepared = prepare_report_input(
            {
                "run_id": "report-context-metadata",
                "lang": "en",
                "metadata": {
                    "run_id": "report-context-metadata",
                    "active_car_snapshot": {
                        "name": "Track Car",
                        "type": "coupe",
                    },
                    "recorded_utc_offset_seconds": 7200,
                },
                "report_date": "2026-03-25T10:00:00Z",
                "record_length": "5m",
                "start_time_utc": "2026-03-25T09:55:00Z",
                "end_time_utc": "2026-03-25T10:00:00Z",
                "sensor_locations": ["front-left", "rear-right"],
                "sensor_locations_connected_throughout": ["rear-right"],
                "sensor_intensity_by_location": [],
                "most_likely_origin": {
                    "location": "rear-right",
                    "suspected_source": "wheel/tire",
                },
                "run_suitability": [],
                "findings": [finding],
                "top_causes": [finding],
            }
        )
        assert prepared.report_facts is not None

        context = report_context.prepare_report_mapping_context(prepared)

        assert context.car_name == "Track Car"
        assert context.car_type == "coupe"
        assert context.date_str == "2026-03-25 12:00:00 UTC+02:00"
        assert context.start_time_utc == "2026-03-25 09:55:00 UTC"
        assert context.end_time_utc == "2026-03-25 10:00:00 UTC"
        assert context.origin is prepared.report_facts.origin
        assert context.origin_location == prepared.report_facts.origin_location
        assert context.sensor_locations_active == ["rear-right"]

    def test_falls_back_to_current_utc_time_when_report_date_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(report_context, "utc_now_iso", lambda: "2026-04-02T03:04:05Z")
        finding = make_finding_payload(finding_id="F001")
        prepared = prepare_report_input(
            {
                "run_id": "report-context-fallback-date",
                "lang": "en",
                "metadata": {},
                "report_date": "",
                "record_length": "",
                "start_time_utc": "",
                "end_time_utc": "",
                "sensor_locations": [],
                "sensor_locations_connected_throughout": [],
                "sensor_intensity_by_location": [],
                "most_likely_origin": {},
                "run_suitability": [],
                "findings": [finding],
                "top_causes": [finding],
            }
        )

        context = report_context.prepare_report_mapping_context(prepared)

        assert context.date_str == "2026-04-02 03:04:05 UTC"


def test_report_context_module_no_longer_reexports_pdf_helper_facade() -> None:
    removed_names = (
        "PrimaryCandidateContext",
        "Report",
        "build_report_from_summary",
        "build_system_cards",
        "compute_location_hotspot_rows",
        "filter_active_sensor_intensity",
        "humanize_signatures",
        "resolve_primary_report_candidate",
    )
    for name in removed_names:
        assert not hasattr(report_context, name)
