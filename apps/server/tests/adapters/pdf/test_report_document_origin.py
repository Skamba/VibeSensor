"""Focused report document projection contracts."""

from __future__ import annotations

import pytest
from test_support.report_helpers import (
    ambiguous_primary_location_summary,
    minimal_summary,
)

from vibesensor.domain import VibrationOrigin
from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.shared.boundaries.summary_fields.finding import finding_from_payload
from vibesensor.shared.boundaries.summary_fields.origin import (
    build_origin_explanation,
)
from vibesensor.use_cases.diagnostics.run_analysis import (
    summarize_origin,
)
from vibesensor.use_cases.history.report_document import build_report_document


def _assert_no_phase_onset(explanation: object) -> None:
    if isinstance(explanation, list):
        assert not any(
            isinstance(part, dict) and part.get("_i18n_key") == "ORIGIN_PHASE_ONSET_NOTE"
            for part in explanation
        )
    else:
        assert isinstance(explanation, dict)


def _origin_explanation(origin: VibrationOrigin) -> object:
    return build_origin_explanation(
        source=str(origin.suspected_source),
        speed_band=origin.speed_band or "",
        location=origin.summary_location,
        dominance=origin.dominance_ratio,
        weak=origin.weak_spatial_separation,
        dominant_phase=origin.dominant_phase or "",
    )


def test_build_report_document_rephrases_ambiguous_primary_locations_as_mixed_signal() -> None:
    data = build_report_document(prepare_report_input(ambiguous_primary_location_summary()))

    expected = "Mixed signal between Front-Left and Rear-Left"

    assert data.verdict_page.inspect_first == expected
    assert data.verdict_page.dominant_corner == expected
    assert data.observed.strongest_location == expected


def test_most_likely_origin_summary_weak_spatial_disambiguates_location() -> None:
    findings = tuple(
        finding_from_payload(p)
        for p in [
            {
                "strongest_location": "Rear Left",
                "location_hotspot": {
                    "top_location": "Rear Left",
                    "ambiguous_locations": ["Rear Left", "Front Right"],
                    "ambiguous_location": True,
                },
                "suspected_source": "wheel/tire",
                "dominance_ratio": 1.05,
                "weak_spatial_separation": True,
                "strongest_speed_band": "80-90 km/h",
                "confidence": 0.81,
            },
            {
                "strongest_location": "Front Right",
                "suspected_source": "wheel/tire",
                "confidence": 0.74,
            },
        ]
    )

    origin = summarize_origin(findings)
    assert origin is not None
    assert origin.summary_location == "Rear Left / Front Right"
    assert origin.alternative_locations == ("Front Right",)


@pytest.mark.parametrize(
    ("phase", "location", "speed_band", "confidence"),
    [
        ("acceleration", "Front Right", "60-80 km/h", 0.75),
        ("deceleration", "Rear Left", "40-60 km/h", 0.70),
    ],
    ids=["acceleration_en", "deceleration_nl"],
)
def test_most_likely_origin_summary_phase_onset(
    phase: str,
    location: str,
    speed_band: str,
    confidence: float,
) -> None:
    findings = tuple(
        finding_from_payload(p)
        for p in [
            {
                "strongest_location": location,
                "suspected_source": "wheel/tire",
                "dominance_ratio": 2.5,
                "weak_spatial_separation": False,
                "strongest_speed_band": speed_band,
                "dominant_phase": phase,
                "confidence": confidence,
            },
        ]
    )

    origin = summarize_origin(findings)
    assert origin is not None

    assert origin.dominant_phase == phase
    explanation = _origin_explanation(origin)
    assert isinstance(explanation, list)
    assert any(
        isinstance(part, dict)
        and part.get("_i18n_key") == "ORIGIN_PHASE_ONSET_NOTE"
        and part.get("phase") == phase
        for part in explanation
    )


def test_most_likely_origin_summary_no_phase_onset_for_cruise() -> None:
    findings = tuple(
        finding_from_payload(p)
        for p in [
            {
                "strongest_location": "Front Left",
                "suspected_source": "wheel/tire",
                "dominance_ratio": 3.0,
                "weak_spatial_separation": False,
                "strongest_speed_band": "80-100 km/h",
                "dominant_phase": "cruise",
                "confidence": 0.80,
            },
        ]
    )

    origin = summarize_origin(findings)
    assert origin is not None
    _assert_no_phase_onset(_origin_explanation(origin))


def test_most_likely_origin_summary_no_phase_onset_when_absent() -> None:
    findings = tuple(
        finding_from_payload(p)
        for p in [
            {
                "strongest_location": "Front Left",
                "suspected_source": "wheel/tire",
                "dominance_ratio": 3.0,
                "weak_spatial_separation": False,
                "strongest_speed_band": "80-100 km/h",
                "confidence": 0.80,
            },
        ]
    )

    origin = summarize_origin(findings)

    assert origin is not None
    assert origin.dominant_phase is None
    _assert_no_phase_onset(_origin_explanation(origin))

    summary = minimal_summary(
        lang="en",
        top_causes=[
            {
                "suspected_source": "wheel/tire",
                "strongest_location": "Rear Left",
                "strongest_speed_band": "80-90 km/h",
                "confidence": 0.83,
                "weak_spatial_separation": True,
                "signatures_observed": ["1x wheel order"],
                "confidence_tone": "warn",
            },
        ],
        most_likely_origin={
            "location": "Rear Left / Front Right",
            "alternative_locations": ["Front Right"],
            "explanation": "Weak spatial separation.",
        },
    )

    data = build_report_document(prepare_report_input(summary))
    assert data.observed.strongest_location == "Mixed signal between Rear-Left and Front-Right"
