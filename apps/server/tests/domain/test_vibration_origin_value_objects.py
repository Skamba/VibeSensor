from __future__ import annotations

from vibesensor.domain import Finding, LocationHotspot, VibrationOrigin, VibrationSource
from vibesensor.shared.boundaries.summary_fields.origin import (
    SuspectedVibrationOrigin,
    origin_payload_from_finding,
    vibration_origin_from_payload,
)


def test_from_analysis_inputs_preserves_typed_contract() -> None:
    hotspot = LocationHotspot.from_analysis_inputs(
        strongest_location="front_left",
        ambiguous=True,
        alternative_locations=["front_right"],
    )
    origin = VibrationOrigin.from_analysis_inputs(
        suspected_source=Finding(suspected_source="wheel/tire").suspected_source,
        hotspot=hotspot,
        dominance_ratio=1.05,
        speed_band="80-90 km/h",
        dominant_phase="acceleration",
        reason="ranked from wheel order evidence",
    )

    assert origin.is_ambiguous is True
    assert origin.summary_location == "front_left / front_right"
    assert origin.alternative_locations == ("front_right",)
    assert origin.weak_spatial_separation is True


def test_vibration_origin_from_payload_uses_boundary_decode() -> None:
    origin = vibration_origin_from_payload(
        {
            "suspected_source": "wheel/tire",
            "strongest_speed_band": "80-90 km/h",
            "dominant_phase": "acceleration",
            "evidence_summary": "payload rationale",
            "dominance_ratio": 1.1,
            "location_hotspot": {
                "top_location": "rear_left",
                "ambiguous_location": True,
                "ambiguous_locations": ["rear_left", "rear_right"],
            },
        }
    )

    assert origin.summary_location == "rear_left / rear_right"
    assert origin.alternative_locations == ("rear_right",)
    assert origin.speed_band == "80-90 km/h"
    assert origin.reason == "payload rationale"


def test_origin_payload_from_finding_projects_canonical_boundary_shape() -> None:
    finding = Finding(
        finding_id="F001",
        suspected_source="wheel/tire",
        strongest_location="front_left",
        strongest_speed_band="80-90 km/h",
        dominance_ratio=1.05,
        weak_spatial_separation=True,
        location=LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            ambiguous=True,
            alternative_locations=["front_right"],
            dominance_ratio=1.05,
        ),
        origin=VibrationOrigin.from_analysis_inputs(
            suspected_source=Finding(suspected_source="wheel/tire").suspected_source,
            hotspot=LocationHotspot.from_analysis_inputs(
                strongest_location="front_left",
                ambiguous=True,
                alternative_locations=["front_right"],
                dominance_ratio=1.05,
            ),
            dominance_ratio=1.05,
            speed_band="80-90 km/h",
            dominant_phase="acceleration",
            reason="domain rationale",
        ),
    )

    payload = origin_payload_from_finding(finding)

    assert payload["location"] == "Front Left / Front Right"
    assert payload["alternative_locations"] == ["front_right"]
    assert payload["suspected_source"] == "wheel/tire"
    assert payload["speed_band"] == "80-90 km/h"
    assert payload["dominant_phase"] == "acceleration"
    assert payload["explanation"] == (
        "domain rationale; speed band 80-90 km/h; dominant phase acceleration"
    )


def test_origin_payload_from_finding_returns_empty_when_no_origin() -> None:
    finding = Finding(finding_id="F002", suspected_source="unknown")
    payload = origin_payload_from_finding(finding)
    assert payload == {}


def test_from_finding_returns_existing_origin() -> None:
    existing_origin = VibrationOrigin.from_analysis_inputs(
        suspected_source=VibrationSource.WHEEL_TIRE,
        dominance_ratio=1.2,
        speed_band="80-90 km/h",
        reason="pre-existing",
    )
    finding = Finding(
        finding_id="F001",
        suspected_source="wheel/tire",
        origin=existing_origin,
    )

    result = VibrationOrigin.from_finding(finding)

    assert result is existing_origin


def test_from_finding_constructs_from_location_hotspot() -> None:
    hotspot = LocationHotspot.from_analysis_inputs(
        strongest_location="front_left",
        ambiguous=False,
    )
    finding = Finding(
        finding_id="F002",
        suspected_source="wheel/tire",
        strongest_speed_band="80-90 km/h",
        dominance_ratio=1.3,
        location=hotspot,
    )

    result = VibrationOrigin.from_finding(finding)

    assert result is not None
    assert result.hotspot is hotspot
    assert result.suspected_source == VibrationSource.WHEEL_TIRE
    assert result.speed_band == "80-90 km/h"
    assert result.dominance_ratio == 1.3


def test_from_finding_constructs_from_strongest_location() -> None:
    finding = Finding(
        finding_id="F003",
        suspected_source="engine",
        strongest_location="rear",
        strongest_speed_band="60-70 km/h",
        dominance_ratio=0.9,
    )

    result = VibrationOrigin.from_finding(finding)

    assert result is not None
    assert result.hotspot is None
    assert result.suspected_source == VibrationSource.ENGINE
    assert result.speed_band == "60-70 km/h"


def test_from_finding_returns_none_when_no_data() -> None:
    finding = Finding(finding_id="F004", suspected_source="unknown")
    assert VibrationOrigin.from_finding(finding) is None


def test_suspected_vibration_origin_is_boundary_type() -> None:
    origin: SuspectedVibrationOrigin = {
        "location": "front_left",
        "suspected_source": "wheel/tire",
    }
    assert origin["location"] == "front_left"
