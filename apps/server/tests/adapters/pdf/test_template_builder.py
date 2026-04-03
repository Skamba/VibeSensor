"""Tests for the focused ReportTemplateData builder."""

from __future__ import annotations

from dataclasses import dataclass, field

from vibesensor.domain import LocationHotspotRow, LocationIntensitySummary
from vibesensor.shared.boundaries.reporting.document import (
    DataTrustItem,
    FindingPresentation,
    NextStep,
    PatternEvidence,
    PeakRow,
    Report,
    SystemFindingCard,
)
from vibesensor.use_cases.history.report_document._candidate_resolver import PrimaryCandidateContext
from vibesensor.use_cases.history.report_document.template_builder import build_template_data


@dataclass
class _StubMetadata:
    car_name: str | None = "TestCar"
    car_type: str | None = "Sedan"


@dataclass
class _StubSummary:
    metadata: _StubMetadata | None = field(default_factory=_StubMetadata)


@dataclass
class _StubReportFacts:
    duration_text: str | None = "60s"
    sample_rate_hz: str | None = "100"
    tire_spec_text: str | None = "205/55R16"
    sample_count: int = 6000
    sensor_locations_active: tuple[str, ...] = ("front", "rear")
    sensor_model: str | None = "MPU6050"
    firmware_version: str | None = "1.2.3"


@dataclass
class _StubPrepared:
    summary: _StubSummary = field(default_factory=_StubSummary)
    report_facts: _StubReportFacts = field(default_factory=_StubReportFacts)


def _make_prepared(**overrides: object) -> _StubPrepared:
    defaults: dict[str, object] = {
        "summary": _StubSummary(),
        "report_facts": _StubReportFacts(),
    }
    defaults.update(overrides)
    return _StubPrepared(**defaults)


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


def _build(**overrides: object):
    """Build a ReportTemplateData with sensible defaults, allowing overrides."""
    defaults: dict[str, object] = {
        "prepared": _make_prepared(),
        "report": _make_report(),
        "report_date_text": "2026-01-01 12:00:00 UTC",
        "report_start_time_utc": "2026-01-01T12:00:00Z",
        "report_end_time_utc": "2026-01-01T12:01:00Z",
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


def test_prepared_metadata_maps_to_template() -> None:
    """Prepared report metadata fields map directly to template data."""
    prepared = _make_prepared(
        report_facts=_StubReportFacts(
            duration_text="90s",
            sample_rate_hz="200",
            tire_spec_text="225/45R17",
            sample_count=18000,
            sensor_model="ICM-42688",
            firmware_version="2.0.0",
            sensor_locations_active=("front", "rear", "trunk"),
        ),
    )
    result = _build(
        prepared=prepared,
        report_date_text="2026-03-25 10:00:00 UTC",
        report_start_time_utc="2026-03-25T10:00:00Z",
        report_end_time_utc="2026-03-25T10:01:30Z",
    )

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


def test_car_name_from_report_overrides_prepared_summary() -> None:
    prepared = _make_prepared(summary=_StubSummary(metadata=_StubMetadata(car_name="ContextCar")))
    report = _make_report(car_name="ReportCar")
    result = _build(prepared=prepared, report=report)

    assert result.car_name == "ReportCar"


def test_car_name_falls_back_to_prepared_summary() -> None:
    prepared = _make_prepared(summary=_StubSummary(metadata=_StubMetadata(car_name="ContextCar")))
    report = _make_report(car_name=None)
    result = _build(prepared=prepared, report=report)

    assert result.car_name == "ContextCar"


def test_car_type_from_report_overrides_prepared_summary() -> None:
    prepared = _make_prepared(summary=_StubSummary(metadata=_StubMetadata(car_type="ContextType")))
    report = _make_report(car_type="ReportType")
    result = _build(prepared=prepared, report=report)

    assert result.car_type == "ReportType"


def test_car_type_falls_back_to_prepared_summary() -> None:
    prepared = _make_prepared(summary=_StubSummary(metadata=_StubMetadata(car_type="ContextType")))
    report = _make_report(car_type=None)
    result = _build(prepared=prepared, report=report)

    assert result.car_type == "ContextType"


def test_primary_sensor_count_maps_to_template() -> None:
    primary = _make_primary(sensor_count=4)
    result = _build(primary=primary)

    assert result.sensor_count == 4


def test_primary_tier_maps_to_certainty_tier_key() -> None:
    primary = _make_primary(tier="C")
    result = _build(primary=primary)

    assert result.certainty_tier_key == "C"


def test_findings_passthrough() -> None:
    findings = [FindingPresentation(suspected_source="wheel/tire")]
    result = _build(findings=findings)

    assert result.findings == findings


def test_top_causes_passthrough() -> None:
    top_causes = [FindingPresentation(suspected_source="engine")]
    result = _build(top_causes=top_causes)

    assert result.top_causes == top_causes


def test_sensor_intensity_passthrough() -> None:
    intensity = [LocationIntensitySummary(location="front", p95_intensity_db=12.5)]
    result = _build(sensor_intensity=intensity)

    assert result.sensor_intensity_by_location == intensity


def test_hotspot_rows_passthrough() -> None:
    rows = [LocationHotspotRow(location="front", peak_value=20.0)]
    result = _build(hotspot_rows=rows)

    assert result.location_hotspot_rows == rows


def test_system_cards_passthrough() -> None:
    cards = [SystemFindingCard(system_name="Engine")]
    result = _build(system_cards=cards)

    assert result.system_cards == cards


def test_next_steps_passthrough() -> None:
    steps = [NextStep(action="Inspect tires")]
    result = _build(next_steps=steps)

    assert result.next_steps == steps


def test_data_trust_passthrough() -> None:
    trust = [DataTrustItem(check="GPS lock", state="pass")]
    result = _build(data_trust=trust)

    assert result.data_trust == trust


def test_peak_rows_passthrough() -> None:
    rows = [PeakRow(rank="1", system="Wheel")]
    result = _build(peak_rows=rows)

    assert result.peak_rows == rows


def test_title_maps() -> None:
    result = _build(title="My Title")

    assert result.title == "My Title"


def test_lang_comes_from_report() -> None:
    report = _make_report(lang="sv")
    result = _build(report=report)

    assert result.lang == "sv"


def test_run_id_comes_from_report() -> None:
    report = _make_report(run_id="custom-run-id")
    result = _build(report=report)

    assert result.run_id == "custom-run-id"
