"""Tests for the focused ReportTemplateData builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from vibesensor.adapters.pdf._candidate_resolver import PrimaryCandidateContext
from vibesensor.adapters.pdf.models import (
    DataTrustItem,
    FindingPresentation,
    NextStep,
    PatternEvidence,
    PeakRow,
    Report,
    SystemFindingCard,
)
from vibesensor.adapters.pdf.template_builder import build_template_data
from vibesensor.domain import LocationHotspotRow, LocationIntensitySummary

if TYPE_CHECKING:
    from vibesensor.adapters.pdf.models import ReportTemplateData
    from vibesensor.adapters.pdf.report_context import ReportMappingContext


@dataclass
class _StubTestRun:
    """Minimal stand-in for a domain TestRun used only by the builder context."""

    findings: list[object] = field(default_factory=list)


def _make_context(**overrides: object) -> ReportMappingContext:
    from vibesensor.adapters.pdf.report_context import ReportMappingContext

    defaults: dict[str, object] = {
        "car_name": "TestCar",
        "car_type": "Sedan",
        "date_str": "2026-01-01 12:00:00 UTC",
        "origin": None,
        "origin_location": "",
        "sensor_locations_active": ["front", "rear"],
        "duration_text": "60s",
        "start_time_utc": "2026-01-01T12:00:00Z",
        "end_time_utc": "2026-01-01T12:01:00Z",
        "sample_rate_hz": "100",
        "tire_spec_text": "205/55R16",
        "sample_count": 6000,
        "sensor_model": "MPU6050",
        "firmware_version": "1.2.3",
        "domain_aggregate": _StubTestRun(),
    }
    defaults.update(overrides)
    return ReportMappingContext(**defaults)


def _make_report(**overrides: object) -> Report:
    defaults: dict[str, object] = {
        "run_id": "run-001",
        "lang": "en",
        "car_name": None,
        "car_type": None,
    }
    defaults.update(overrides)
    return Report(**defaults)


def _make_primary(**overrides: object) -> PrimaryCandidateContext:
    defaults: dict[str, object] = {
        "primary_candidate": None,
        "primary_source": "wheel/tire",
        "primary_system": "Wheel/Tire",
        "primary_location": "front_left",
        "primary_speed": "60-80",
        "confidence": 0.85,
        "sensor_count": 2,
        "weak_spatial": False,
        "has_reference_gaps": False,
        "strength_db": 25.0,
        "strength_text": "Moderate",
        "strength_band_key": "moderate",
        "certainty_key": "B",
        "certainty_label_text": "Probable",
        "certainty_pct": "85%",
        "certainty_reason": "Strong match",
        "tier": "B",
    }
    defaults.update(overrides)
    return PrimaryCandidateContext(**defaults)


def _build(**overrides: object) -> ReportTemplateData:
    """Build a ReportTemplateData with sensible defaults, allowing overrides."""
    defaults: dict[str, object] = {
        "context": _make_context(),
        "report": _make_report(),
        "primary": _make_primary(),
        "title": "Test Report",
        "observed": PatternEvidence(),
        "system_cards": [],
        "next_steps": [],
        "data_trust": [],
        "pattern_evidence": PatternEvidence(),
        "peak_rows": [],
        "findings": [],
        "top_causes": [],
        "sensor_intensity": [],
        "hotspot_rows": [],
    }
    defaults.update(overrides)
    return build_template_data(**defaults)


# ---------------------------------------------------------------------------
# Context metadata mapping
# ---------------------------------------------------------------------------


def test_context_metadata_maps_to_template() -> None:
    """Context-owned run metadata fields map directly to template data."""
    ctx = _make_context(
        date_str="2026-03-25 10:00:00 UTC",
        duration_text="90s",
        start_time_utc="2026-03-25T10:00:00Z",
        end_time_utc="2026-03-25T10:01:30Z",
        sample_rate_hz="200",
        tire_spec_text="225/45R17",
        sample_count=18000,
        sensor_model="ICM-42688",
        firmware_version="2.0.0",
        sensor_locations_active=["front", "rear", "trunk"],
    )
    result = _build(context=ctx)

    assert result.run_datetime == "2026-03-25 10:00:00 UTC"
    assert result.duration_text == "90s"
    assert result.start_time_utc == "2026-03-25T10:00:00Z"
    assert result.end_time_utc == "2026-03-25T10:01:30Z"
    assert result.sample_rate_hz == "200"
    assert result.tire_spec_text == "225/45R17"
    assert result.sample_count == 18000
    assert result.sensor_model == "ICM-42688"
    assert result.firmware_version == "2.0.0"
    assert result.sensor_locations == ["front", "rear", "trunk"]


# ---------------------------------------------------------------------------
# Car name/type fallback logic
# ---------------------------------------------------------------------------


def test_car_name_from_report_overrides_context() -> None:
    """Report.car_name takes precedence over context.car_name."""
    ctx = _make_context(car_name="ContextCar")
    report = _make_report(car_name="ReportCar")
    result = _build(context=ctx, report=report)

    assert result.car_name == "ReportCar"


def test_car_name_falls_back_to_context() -> None:
    """When report.car_name is None, context.car_name is used."""
    ctx = _make_context(car_name="ContextCar")
    report = _make_report(car_name=None)
    result = _build(context=ctx, report=report)

    assert result.car_name == "ContextCar"


def test_car_type_from_report_overrides_context() -> None:
    """Report.car_type takes precedence over context.car_type."""
    ctx = _make_context(car_type="ContextType")
    report = _make_report(car_type="ReportType")
    result = _build(context=ctx, report=report)

    assert result.car_type == "ReportType"


def test_car_type_falls_back_to_context() -> None:
    """When report.car_type is None, context.car_type is used."""
    ctx = _make_context(car_type="ContextType")
    report = _make_report(car_type=None)
    result = _build(context=ctx, report=report)

    assert result.car_type == "ContextType"


# ---------------------------------------------------------------------------
# Primary candidate fields
# ---------------------------------------------------------------------------


def test_primary_sensor_count_maps_to_template() -> None:
    """Primary candidate sensor_count maps to template sensor_count."""
    primary = _make_primary(sensor_count=4)
    result = _build(primary=primary)

    assert result.sensor_count == 4


def test_primary_tier_maps_to_certainty_tier_key() -> None:
    """Primary candidate tier maps to certainty_tier_key."""
    primary = _make_primary(tier="C")
    result = _build(primary=primary)

    assert result.certainty_tier_key == "C"


# ---------------------------------------------------------------------------
# Section passthrough
# ---------------------------------------------------------------------------


def test_findings_passthrough() -> None:
    """Findings list is passed through without modification."""
    findings = [FindingPresentation(suspected_source="wheel/tire")]
    result = _build(findings=findings)

    assert result.findings == findings


def test_top_causes_passthrough() -> None:
    """Top causes list is passed through without modification."""
    top_causes = [FindingPresentation(suspected_source="engine")]
    result = _build(top_causes=top_causes)

    assert result.top_causes == top_causes


def test_sensor_intensity_passthrough() -> None:
    """Sensor intensity list is passed through without modification."""
    intensity = [LocationIntensitySummary(location="front", p95_intensity_db=12.5)]
    result = _build(sensor_intensity=intensity)

    assert result.sensor_intensity_by_location == intensity


def test_hotspot_rows_passthrough() -> None:
    """Hotspot rows are passed through without modification."""
    rows = [LocationHotspotRow(location="front", peak_value=20.0)]
    result = _build(hotspot_rows=rows)

    assert result.location_hotspot_rows == rows


def test_system_cards_passthrough() -> None:
    """System cards are passed through without modification."""
    cards = [SystemFindingCard(system_name="Engine")]
    result = _build(system_cards=cards)

    assert result.system_cards == cards


def test_next_steps_passthrough() -> None:
    """Next steps are passed through without modification."""
    steps = [NextStep(action="Inspect tires")]
    result = _build(next_steps=steps)

    assert result.next_steps == steps


def test_data_trust_passthrough() -> None:
    """Data trust items are passed through without modification."""
    trust = [DataTrustItem(check="GPS lock", state="pass")]
    result = _build(data_trust=trust)

    assert result.data_trust == trust


def test_peak_rows_passthrough() -> None:
    """Peak rows are passed through without modification."""
    rows = [PeakRow(rank="1", system="Wheel")]
    result = _build(peak_rows=rows)

    assert result.peak_rows == rows


# ---------------------------------------------------------------------------
# Scalar fields
# ---------------------------------------------------------------------------


def test_title_maps() -> None:
    """Title is passed through."""
    result = _build(title="My Title")

    assert result.title == "My Title"


def test_lang_comes_from_report() -> None:
    """Language is sourced from the Report, not the context."""
    report = _make_report(lang="sv")
    result = _build(report=report)

    assert result.lang == "sv"


def test_run_id_comes_from_report() -> None:
    """run_id is sourced from the Report."""
    report = _make_report(run_id="custom-run-id")
    result = _build(report=report)

    assert result.run_id == "custom-run-id"
