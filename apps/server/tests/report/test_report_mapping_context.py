"""Tests for the enhanced ReportMappingContext with behavior methods."""

from __future__ import annotations

import pytest

from vibesensor.report.mapping import (
    PrimaryCandidateContext,
    ReportMappingContext,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(**overrides: object) -> ReportMappingContext:
    """Build a minimal ReportMappingContext with overrides."""
    defaults: dict[str, object] = {
        "meta": {},
        "car_name": None,
        "car_type": None,
        "date_str": "2025-01-01 12:00:00 UTC",
        "top_causes": [],
        "findings_non_ref": [],
        "findings": [],
        "speed_stats": {
            "min_kmh": None,
            "max_kmh": None,
            "mean_kmh": None,
            "stddev_kmh": None,
            "range_kmh": None,
            "steady_speed": False,
        },
        "origin": {
            "location": "unknown",
            "alternative_locations": [],
            "source": "unknown",
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
    return ReportMappingContext(**defaults)  # type: ignore[arg-type]


def _make_cause(**overrides: object) -> dict:
    """Build a minimal cause dict."""
    base = {
        "finding_id": "F001",
        "source": "wheel/tire",
        "confidence": 0.75,
        "strongest_location": "front_left",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------


class TestTopReportCandidate:
    def test_returns_first_top_cause(self) -> None:
        cause = _make_cause(finding_id="F001")
        context = _make_context(top_causes=[cause, _make_cause(finding_id="F002")])
        assert context.top_report_candidate() is cause

    def test_falls_back_to_first_non_ref_finding(self) -> None:
        finding = _make_cause(finding_id="F001")
        context = _make_context(top_causes=[], findings_non_ref=[finding])
        assert context.top_report_candidate() is finding

    def test_returns_none_when_empty(self) -> None:
        context = _make_context()
        assert context.top_report_candidate() is None


class TestPrimaryHotspot:
    def test_returns_first_cause(self) -> None:
        cause = _make_cause()
        context = _make_context(top_causes=[cause])
        assert context.primary_hotspot() is cause

    def test_returns_none_when_no_causes(self) -> None:
        context = _make_context()
        assert context.primary_hotspot() is None


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


class TestDisplayDuration:
    def test_with_duration(self) -> None:
        context = _make_context(duration_text="2m 30s")
        assert context.display_duration() == "2m 30s"

    def test_none_duration(self) -> None:
        context = _make_context(duration_text=None)
        assert context.display_duration() is None


class TestDisplaySpeedRange:
    def test_with_speed_range(self) -> None:
        context = _make_context(
            speed_stats={
                "min_kmh": 40.0,
                "max_kmh": 120.0,
                "mean_kmh": 80.0,
                "stddev_kmh": 20.0,
                "range_kmh": 80.0,
                "steady_speed": False,
            },
        )
        assert context.display_speed_range() == "40\u2013120 km/h"

    def test_missing_speed_data(self) -> None:
        context = _make_context(
            speed_stats={
                "min_kmh": None,
                "max_kmh": None,
                "mean_kmh": None,
                "stddev_kmh": None,
                "range_kmh": None,
                "steady_speed": False,
            },
        )
        assert context.display_speed_range() is None


# ---------------------------------------------------------------------------
# Intensity queries
# ---------------------------------------------------------------------------


class TestHasSignificantLocationIntensity:
    def test_with_positive_intensity(self) -> None:
        context = _make_context()
        rows = [{"location": "front_left", "p95_intensity_db": 12.5}]
        assert context.has_significant_location_intensity(rows) is True

    def test_with_zero_intensity(self) -> None:
        context = _make_context()
        rows = [{"location": "front_left", "p95_intensity_db": 0.0}]
        assert context.has_significant_location_intensity(rows) is False

    def test_with_empty_rows(self) -> None:
        context = _make_context()
        assert context.has_significant_location_intensity([]) is False

    def test_with_non_dict_rows(self) -> None:
        context = _make_context()
        assert context.has_significant_location_intensity(["not a dict"]) is False  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# Observed signature
# ---------------------------------------------------------------------------


class TestObservedSignature:
    def test_builds_from_primary(self) -> None:
        context = _make_context()
        primary = PrimaryCandidateContext(
            primary_candidate=_make_cause(),
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
        sig = context.observed_signature(primary)
        assert sig.primary_system == "Wheel / Tire"
        assert sig.strongest_sensor_location == "front_left"
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
