"""Tests for dropping non-finite numeric values while decoding boundary payloads."""

from __future__ import annotations

from vibesensor.shared.boundaries.summary_fields.finding import finding_from_payload
from vibesensor.shared.boundaries.summary_fields.origin import location_hotspot_from_payload


def test_location_hotspot_from_payload_drops_non_finite_numeric_values() -> None:
    hotspot = location_hotspot_from_payload(
        {
            "top_location": "front-left",
            "dominance_ratio": float("nan"),
            "localization_confidence": float("inf"),
            "location_count": float("-inf"),
        }
    )

    assert hotspot.strongest_location == "front-left"
    assert hotspot.dominance_ratio is None
    assert hotspot.localization_confidence is None
    assert hotspot.location_count is None


def test_finding_from_payload_drops_non_finite_boundary_numbers() -> None:
    finding = finding_from_payload(
        {
            "finding_id": "F-boundary-numbers",
            "suspected_source": "wheel/tire",
            "confidence": float("nan"),
            "ranking_score": float("inf"),
            "dominance_ratio": float("-inf"),
            "phase_evidence": {"cruise_fraction": float("nan")},
            "evidence_metrics": {"vibration_strength_db": float("inf")},
            "location_hotspot": {
                "top_location": "front-left",
                "dominance_ratio": float("nan"),
                "localization_confidence": float("inf"),
                "location_count": float("-inf"),
            },
        }
    )

    assert finding.confidence is None
    assert finding.ranking_score == 0.0
    assert finding.dominance_ratio is None
    assert finding.cruise_fraction == 0.0
    assert finding.vibration_strength_db is None
    assert finding.location is not None
    assert finding.location.dominance_ratio is None
    assert finding.location.localization_confidence is None
    assert finding.location.location_count is None
