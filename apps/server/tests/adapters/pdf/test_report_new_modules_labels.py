"""Focused tests for report label and pattern helper modules."""

from __future__ import annotations

import pytest

from vibesensor.domain.confidence_assessment import ConfidenceAssessment
from vibesensor.shared.boundaries.reporting import FindingPresentation
from vibesensor.shared.report_presentation import (
    order_label_human,
    peak_classification_text,
    strength_label,
    strength_text,
)
from vibesensor.use_cases.history.report_document.pattern_parts import (
    parts_for_pattern,
    why_parts_listed,
)
from vibesensor.use_cases.history.report_document.peak_table import (
    build_peak_row,
    peak_row_system_label,
)


@pytest.mark.parametrize(
    ("db_val", "expected_key"),
    [
        (None, "unknown"),
        (0.0, "negligible"),
        (5.0, "negligible"),
        (8.0, "light"),
        (15.9, "light"),
        (16.0, "moderate"),
        (25.9, "moderate"),
        (26.0, "strong"),
        (35.9, "strong"),
        (36.0, "very_strong"),
        (100.0, "very_strong"),
    ],
)
def test_strength_label_bands(db_val: float | None, expected_key: str) -> None:
    key, label = strength_label(db_val, lang="en")
    assert key == expected_key
    assert isinstance(label, str) and label


def test_strength_label_nl() -> None:
    key, label = strength_label(20.0, lang="nl")
    assert key == "moderate"
    assert label == "Matig"


def test_strength_text_none() -> None:
    assert "Unknown" in strength_text(None, lang="en")


def test_strength_text_value() -> None:
    txt = strength_text(22.0, lang="en")
    assert "Moderate" in txt
    assert "22.0 dB" in txt


def test_order_label_human_localizes_order_names() -> None:
    assert order_label_human("en", "1x wheel") == "1x wheel order"
    assert order_label_human("nl", "2x engine") == "2x motororde"


def test_peak_classification_text_uses_translations() -> None:
    translated = peak_classification_text(
        "persistent",
        tr=lambda key, **_kw: {
            "CLASSIFICATION_PERSISTENT": "Persistent",
            "UNKNOWN": "Unknown",
        }[key],
    )
    assert translated == "Persistent"


def test_build_peak_row_transient_meaning_uses_brief_event_label() -> None:
    row = build_peak_row(
        {
            "rank": 1,
            "frequency_hz": 95.0,
            "order_label": "",
            "p95_intensity_db": 18.0,
            "strength_db": 18.0,
            "presence_ratio": 0.2,
            "peak_classification": "transient",
            "typical_speed_band": "any",
        },
        lang="en",
        tr=lambda key, **_kw: {
            "CLASSIFICATION_TRANSIENT": "Intermittent",
            "PEAK_ROW_BRIEF_EVENT": "Brief event",
            "SOURCE_TRANSIENT_IMPACT": "Transient impact",
            "UNKNOWN": "Unknown",
        }[key],
    )
    assert row.relevance == "Brief event"


def test_build_peak_row_high_presence_transient_uses_repeatability_label() -> None:
    row = build_peak_row(
        {
            "rank": 1,
            "frequency_hz": 95.0,
            "order_label": "",
            "p95_intensity_db": 18.0,
            "strength_db": 18.0,
            "presence_ratio": 0.8,
            "peak_classification": "transient",
            "typical_speed_band": "any",
        },
        lang="en",
        tr=lambda key, **_kw: {
            "CLASSIFICATION_TRANSIENT": "Intermittent",
            "PEAK_ROW_BRIEF_EVENT": "Brief event",
            "PEAK_ROW_REPEATED_PATTERN": "Repeated pattern",
            "PEAK_ROW_SEEN_MORE_THAN_ONCE": "Seen more than once",
            "SOURCE_TRANSIENT_IMPACT": "Transient impact",
            "UNKNOWN": "Unknown",
        }[key],
    )
    assert row.relevance == "Repeated pattern"


def test_peak_row_system_label_falls_back_to_matching_finding_order() -> None:
    label = peak_row_system_label(
        {
            "frequency_hz": 11.0,
            "order_label": "1x wheel",
            "suspected_source": "",
        },
        findings=[
            FindingPresentation(
                suspected_source="wheel/tire",
                order="1x wheel",
                frequency_hz=10.9,
            )
        ],
        tr=lambda key, **_kw: {
            "SOURCE_WHEEL_TIRE": "Wheel / Tire",
        }[key],
    )
    assert label == "Wheel / Tire"


@pytest.mark.parametrize(
    ("conf", "expected_label_key"),
    [
        (0.0, "CONFIDENCE_LOW"),
        (0.39, "CONFIDENCE_LOW"),
        (0.40, "CONFIDENCE_MEDIUM"),
        (0.69, "CONFIDENCE_MEDIUM"),
        (0.70, "CONFIDENCE_HIGH"),
        (1.0, "CONFIDENCE_HIGH"),
    ],
)
def test_confidence_assessment_levels(conf: float, expected_label_key: str) -> None:
    ca = ConfidenceAssessment.assess(conf)
    assert ca.label_key == expected_label_key
    assert isinstance(ca.pct_text, str) and "%" in ca.pct_text


def test_confidence_assessment_single_sensor_reason() -> None:
    ca = ConfidenceAssessment.assess(0.80, sensor_count=1)
    assert "single sensor" in ca.reason.lower() or "sensor" in ca.reason.lower()


def test_confidence_assessment_reference_gaps_reason() -> None:
    ca = ConfidenceAssessment.assess(0.80, has_reference_gaps=True)
    assert "reference" in ca.reason.lower()


def test_confidence_assessment_weak_spatial_reason() -> None:
    ca = ConfidenceAssessment.assess(0.80, weak_spatial=True)
    assert "spatial" in ca.reason.lower() or "location" in ca.reason.lower()


def test_confidence_assessment_negligible_strength_caps_high() -> None:
    ca = ConfidenceAssessment.assess(0.80, strength_band_key="negligible")
    assert ca.label_key == "CONFIDENCE_MEDIUM"
    assert ca.downgraded


def test_parts_for_wheel_1x() -> None:
    parts = parts_for_pattern("wheel/tire", "1x wheel order")
    assert len(parts) >= 2
    assert any("flat spot" in part.lower() or "bearing" in part.lower() for part in parts)


def test_parts_for_driveline_wildcard() -> None:
    parts = parts_for_pattern("driveline", None)
    assert len(parts) >= 2


def test_parts_for_engine_2x_nl() -> None:
    parts = parts_for_pattern("engine", "2x engine order", lang="nl")
    assert len(parts) >= 2
    assert all(isinstance(part, str) and part for part in parts)


def test_parts_for_unknown_system() -> None:
    parts = parts_for_pattern("unknown_system", "1x")
    assert len(parts) >= 1


def test_why_parts_listed_en() -> None:
    text = why_parts_listed("wheel/tire", "1x wheel order")
    assert "1x" in text
    assert "wheel" in text.lower()


def test_why_parts_listed_nl() -> None:
    text = why_parts_listed("engine", "2x engine order", lang="nl")
    assert "2x" in text
    assert "motor" in text.lower()
