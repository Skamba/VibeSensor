"""Tests for report_data.py from_dict() deserialization methods."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from vibesensor.report.report_data import (
    CarMeta,
    DataTrustItem,
    NextStep,
    ObservedSignature,
    PartSuggestion,
    PatternEvidence,
    PeakRow,
    ReportTemplateData,
    SystemFindingCard,
)

# ---------------------------------------------------------------------------
# Parametrized roundtrip tests — validates from_dict(asdict(x)) == x
# ---------------------------------------------------------------------------

_ROUNDTRIP_CASES = [
    pytest.param(
        ObservedSignature,
        {
            "primary_system": "wheel bearing",
            "strongest_sensor_location": "front-left",
            "speed_band": "80-120 km/h",
        },
        id="ObservedSignature",
    ),
    pytest.param(
        NextStep,
        {"action": "Inspect", "rank": 1, "speed_band": "60-80 km/h"},
        id="NextStep",
    ),
    pytest.param(
        DataTrustItem,
        {"check": "speed_coverage", "state": "pass", "detail": "OK"},
        id="DataTrustItem",
    ),
    pytest.param(
        PeakRow,
        {
            "rank": "1",
            "system": "wheel",
            "freq_hz": "42.3",
            "order": "1x",
            "peak_db": "15.2",
            "strength_db": "12.0",
            "speed_band": "80-100 km/h",
            "relevance": "high",
        },
        id="PeakRow",
    ),
]


@pytest.mark.parametrize("cls, kwargs", _ROUNDTRIP_CASES)
def test_from_dict_roundtrip(cls, kwargs) -> None:  # type: ignore[type-arg]
    original = cls(**kwargs)
    assert cls.from_dict(asdict(original)) == original


class TestCarMetaFromDict:
    def test_from_dict(self) -> None:
        result = CarMeta.from_dict({"name": "BMW", "car_type": "sedan"})
        assert result.name == "BMW"
        assert result.car_type == "sedan"

    def test_from_none(self) -> None:
        result = CarMeta.from_dict(None)
        assert result.name is None
        assert result.car_type is None

    def test_from_empty(self) -> None:
        result = CarMeta.from_dict({})
        assert result.name is None

    def test_ignores_extra_keys(self) -> None:
        result = CarMeta.from_dict({"name": "BMW", "unknown_key": 42})
        assert result.name == "BMW"


class TestPartSuggestionFromDict:
    def test_from_dict(self) -> None:
        result = PartSuggestion.from_dict({"name": "Bearing", "why_shown": "matched"})
        assert result.name == "Bearing"
        assert result.why_shown == "matched"

    def test_from_string(self) -> None:
        result = PartSuggestion.from_dict("Tire")
        assert result.name == "Tire"

    def test_from_none(self) -> None:
        result = PartSuggestion.from_dict(None)
        assert result.name == "None"


class TestSystemFindingCardFromDict:
    def test_with_parts(self) -> None:
        d = {
            "system_name": "Wheel Bearing",
            "parts": [{"name": "Part A"}, {"name": "Part B"}],
        }
        result = SystemFindingCard.from_dict(d)
        assert result.system_name == "Wheel Bearing"
        assert len(result.parts) == 2
        assert result.parts[0].name == "Part A"
        assert result.parts[1].name == "Part B"

    def test_without_parts(self) -> None:
        result = SystemFindingCard.from_dict({"system_name": "Engine"})
        assert result.system_name == "Engine"
        assert result.parts == []

    def test_from_none(self) -> None:
        result = SystemFindingCard.from_dict(None)
        assert result.system_name == ""


class TestReportTemplateDataFromDict:
    def test_full_roundtrip(self) -> None:
        original = ReportTemplateData(
            title="Test Report",
            run_id="run-123",
            sample_count=100,
            sensor_count=4,
            car=CarMeta(name="BMW"),
            observed=ObservedSignature(primary_system="wheel bearing"),
            system_cards=[
                SystemFindingCard(
                    system_name="Bearing",
                    parts=[PartSuggestion(name="Part A")],
                ),
            ],
            next_steps=[NextStep(action="Inspect", rank=1)],
            data_trust=[DataTrustItem(check="speed", state="pass")],
            pattern_evidence=PatternEvidence(strongest_location="FL"),
            peak_rows=[
                PeakRow(
                    rank="1",
                    system="wheel",
                    freq_hz="42",
                    order="1x",
                    peak_db="15",
                    strength_db="12",
                    speed_band="80-100",
                    relevance="high",
                ),
            ],
            lang="en",
            certainty_tier_key="B",
        )
        d = asdict(original)
        result = ReportTemplateData.from_dict(d)
        assert result.title == "Test Report"
        assert result.run_id == "run-123"
        assert result.car.name == "BMW"
        assert result.observed.primary_system == "wheel bearing"
        assert len(result.system_cards) == 1
        assert result.system_cards[0].parts[0].name == "Part A"
        assert len(result.next_steps) == 1
        assert len(result.data_trust) == 1
        assert result.pattern_evidence.strongest_location == "FL"
        assert len(result.peak_rows) == 1
        assert result.lang == "en"
        assert result.certainty_tier_key == "B"

    def test_empty_dict(self) -> None:
        result = ReportTemplateData.from_dict({})
        assert result.title == ""
        assert result.car == CarMeta()
        assert result.system_cards == []

    def test_ignores_extra_keys(self) -> None:
        result = ReportTemplateData.from_dict({"title": "Test", "unknown": 42})
        assert result.title == "Test"
