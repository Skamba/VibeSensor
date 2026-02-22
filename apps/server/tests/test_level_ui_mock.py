# ruff: noqa: E501
"""UI mock test – lightweight deterministic validation.

Mocks a stable analysis response and verifies that the API response
model carries the expected fields: source, corner, confidence, speed band,
and warnings.  No browser/Selenium needed.
"""

from __future__ import annotations

from typing import Any

from builders import (
    SENSOR_FL,
    make_fault_samples,
    make_noise_samples,
    run_analysis,
)


def _build_stable_analysis() -> dict[str, Any]:
    """Build a deterministic analysis summary for UI assertion."""
    sensors = ["front-left", "front-right", "rear-left", "rear-right"]
    samples: list[dict[str, Any]] = []
    samples.extend(make_noise_samples(sensors=sensors, speed_kmh=80.0, n_samples=10))
    samples.extend(
        make_fault_samples(
            fault_sensor=SENSOR_FL,
            sensors=sensors,
            speed_kmh=80.0,
            n_samples=40,
            fault_amp=0.08,
            fault_vib_db=30.0,
        )
    )
    return run_analysis(samples)


def test_ui_analysis_fields() -> None:
    """Verify the analysis response carries key UI fields."""
    summary = _build_stable_analysis()

    # --- Top-level structure ---
    assert isinstance(summary, dict)
    assert "top_causes" in summary, "Missing 'top_causes' in summary"
    assert "speed_breakdown" in summary, "Missing 'speed_breakdown' in summary"

    # --- Top cause fields ---
    causes = summary["top_causes"]
    assert isinstance(causes, list) and len(causes) > 0, "No top causes found"
    top = causes[0]
    assert "source" in top, "Missing 'source' in top cause"
    assert "confidence" in top, "Missing 'confidence' in top cause"
    assert isinstance(top["confidence"], (int, float)), "Confidence must be numeric"
    assert 0 <= top["confidence"] <= 1, f"Confidence out of range: {top['confidence']}"

    # --- Confidence label inside top cause ---
    assert "confidence_label_key" in top, "Missing 'confidence_label_key' in top cause"
    assert "confidence_tone" in top, "Missing 'confidence_tone' in top cause"
    assert top["confidence_tone"] in ("success", "warn", "neutral"), (
        f"Invalid tone: {top['confidence_tone']}"
    )
    assert top["confidence_label_key"] in (
        "CONFIDENCE_HIGH",
        "CONFIDENCE_MEDIUM",
        "CONFIDENCE_LOW",
    ), f"Invalid label: {top['confidence_label_key']}"

    # --- Speed breakdown ---
    sb = summary["speed_breakdown"]
    assert isinstance(sb, list), "speed_breakdown must be a list"
    assert len(sb) > 0, "speed_breakdown is empty"
    for band in sb:
        assert "speed_range" in band, f"Missing 'speed_range' in band: {band}"

    # --- Strongest speed band in top cause ---
    assert "strongest_speed_band" in top, "Missing 'strongest_speed_band' in top cause"

    # --- Findings list ---
    assert "findings" in summary, "Missing 'findings' in summary"
    findings = summary["findings"]
    assert isinstance(findings, list), "findings must be a list"

    # --- Data quality ---
    assert "data_quality" in summary, "Missing 'data_quality' in summary"
    dq = summary["data_quality"]
    assert isinstance(dq, dict), "data_quality must be a dict"

    # --- Most likely origin ---
    origin = summary.get("most_likely_origin")
    assert origin is not None, "Missing 'most_likely_origin' in summary"
    assert isinstance(origin, dict)
    assert "source" in origin, "most_likely_origin must have 'source'"
    assert "location" in origin, "most_likely_origin must have 'location'"

    # --- Warnings (may be empty) ---
    assert "warnings" in summary, "Missing 'warnings' in summary"
