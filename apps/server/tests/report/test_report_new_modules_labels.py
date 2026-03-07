"""Focused tests for report label and pattern helper modules."""

from __future__ import annotations

import pytest

from vibesensor.analysis.pattern_parts import parts_for_pattern, why_parts_listed
from vibesensor.analysis.strength_labels import certainty_label, strength_label, strength_text


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


@pytest.mark.parametrize(
    ("conf", "expected_level"),
    [
        (0.0, "low"),
        (0.39, "low"),
        (0.40, "medium"),
        (0.69, "medium"),
        (0.70, "high"),
        (1.0, "high"),
    ],
)
def test_certainty_label_levels(conf: float, expected_level: str) -> None:
    level, label, pct, reason = certainty_label(conf, lang="en")
    assert level == expected_level
    assert isinstance(label, str) and label
    assert "%" in pct
    assert isinstance(reason, str) and reason


def test_certainty_label_nl() -> None:
    _, label, _, _ = certainty_label(0.80, lang="nl")
    assert label == "Hoog"


def test_certainty_single_sensor_reason() -> None:
    _, _, _, reason = certainty_label(0.80, lang="en", sensor_count=1)
    assert "single sensor" in reason.lower()


def test_certainty_reference_gaps_reason() -> None:
    _, _, _, reason = certainty_label(0.80, lang="en", has_reference_gaps=True)
    assert "reference" in reason.lower()


def test_certainty_narrow_speed_reason() -> None:
    _, _, _, reason = certainty_label(0.80, lang="en", steady_speed=True)
    assert "speed" in reason.lower()


def test_certainty_weak_spatial_reason() -> None:
    _, _, _, reason = certainty_label(0.80, lang="en", weak_spatial=True)
    assert "spatial" in reason.lower()


def test_certainty_negligible_strength_caps_high_label() -> None:
    level, label, _, _ = certainty_label(0.80, lang="en", strength_band_key="negligible")
    assert level == "medium"
    assert label == "Medium"


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
