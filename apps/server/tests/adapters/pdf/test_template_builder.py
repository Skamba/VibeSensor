"""Tests for canonical report-document context mapping."""

from __future__ import annotations

from vibesensor.domain import LocationHotspotRow, LocationIntensitySummary
from vibesensor.shared.boundaries.reporting import FindingPresentation
from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    AppendixBData,
    AppendixCData,
    AppendixDData,
    DataTrustItem,
    NextStep,
    PatternEvidence,
    PeakRow,
    ReportDocumentContext,
    SystemFindingCard,
    VerdictPageData,
)
from vibesensor.use_cases.history.report_document import build_report_document_data


def _make_context(**overrides: object) -> ReportDocumentContext:
    defaults: dict[str, object] = {
        "title": "Test Report",
        "run_datetime": "2026-01-01 12:00:00 UTC",
        "run_id": "run-001",
        "duration_text": "60s",
        "start_time_utc": "2026-01-01T12:00:00Z",
        "end_time_utc": "2026-01-01T12:01:00Z",
        "sample_rate_hz": "100",
        "tire_spec_text": "205/55R16",
        "sample_count": 6000,
        "sensor_count": 2,
        "sensor_locations": ("front", "rear"),
        "sensor_model": "MPU6050",
        "firmware_version": "1.2.3",
        "car_name": "TestCar",
        "car_type": "Sedan",
        "observed": PatternEvidence(),
        "system_cards": (),
        "next_steps": (),
        "data_trust": (),
        "pattern_evidence": PatternEvidence(),
        "peak_rows": (),
        "language": "en",
        "certainty_tier_key": "B",
        "findings": (),
        "top_causes": (),
        "sensor_intensity_by_location": (),
        "location_hotspot_rows": (),
        "verdict_page": VerdictPageData(),
        "appendix_a": AppendixAData(),
        "appendix_b": AppendixBData(),
        "appendix_c": AppendixCData(),
        "appendix_d": AppendixDData(),
    }
    defaults.update(overrides)
    return ReportDocumentContext(**defaults)


def _build(**overrides: object):
    return build_report_document_data(_make_context(**overrides))


def test_run_metadata_maps_to_template() -> None:
    result = _build(
        run_datetime="2026-03-25 10:00:00 UTC",
        duration_text="90s",
        start_time_utc="2026-03-25T10:00:00Z",
        end_time_utc="2026-03-25T10:01:30Z",
        sample_rate_hz="200",
        tire_spec_text="225/45R17",
        sample_count=18000,
        sensor_model="ICM-42688",
        firmware_version="2.0.0",
        sensor_locations=("front", "rear", "trunk"),
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


def test_car_fields_map() -> None:
    result = _build(car_name="ReportCar", car_type="ReportType")

    assert result.car_name == "ReportCar"
    assert result.car_type == "ReportType"


def test_sensor_count_maps_to_template() -> None:
    result = _build(sensor_count=4)

    assert result.sensor_count == 4


def test_certainty_tier_key_maps() -> None:
    result = _build(certainty_tier_key="C")

    assert result.certainty_tier_key == "C"


def test_findings_passthrough() -> None:
    findings = (FindingPresentation(suspected_source="wheel/tire"),)
    result = _build(findings=findings)

    assert result.findings == list(findings)


def test_top_causes_passthrough() -> None:
    top_causes = (FindingPresentation(suspected_source="engine"),)
    result = _build(top_causes=top_causes)

    assert result.top_causes == list(top_causes)


def test_sensor_intensity_passthrough() -> None:
    intensity = (LocationIntensitySummary(location="front", p95_intensity_db=12.5),)
    result = _build(sensor_intensity_by_location=intensity)

    assert result.sensor_intensity_by_location == list(intensity)


def test_hotspot_rows_passthrough() -> None:
    rows = (LocationHotspotRow(location="front", peak_value=20.0),)
    result = _build(location_hotspot_rows=rows)

    assert result.location_hotspot_rows == list(rows)


def test_system_cards_passthrough() -> None:
    cards = (SystemFindingCard(system_name="Engine"),)
    result = _build(system_cards=cards)

    assert result.system_cards == list(cards)


def test_next_steps_passthrough() -> None:
    steps = (NextStep(action="Inspect tires"),)
    result = _build(next_steps=steps)

    assert result.next_steps == list(steps)


def test_data_trust_passthrough() -> None:
    trust = (DataTrustItem(check="GPS lock", state="pass"),)
    result = _build(data_trust=trust)

    assert result.data_trust == list(trust)


def test_peak_rows_passthrough() -> None:
    rows = (PeakRow(rank="1", system="Wheel"),)
    result = _build(peak_rows=rows)

    assert result.peak_rows == list(rows)


def test_title_maps() -> None:
    result = _build(title="My Title")

    assert result.title == "My Title"


def test_language_maps() -> None:
    result = _build(language="sv")

    assert result.lang == "sv"


def test_run_id_maps() -> None:
    result = _build(run_id="custom-run-id")

    assert result.run_id == "custom-run-id"
