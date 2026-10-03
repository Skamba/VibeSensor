"""The persisted diagnosis block: verdict, confidence level, order label, mg amplitudes, zone."""

from __future__ import annotations

from typing import Any

import pytest
from test_support.analysis import run_analysis
from test_support.core import standard_metadata, wheel_hz
from test_support.fault_scenarios import (
    make_engine_order_samples,
    make_fault_samples,
    make_speed_sweep_fault_samples,
)
from test_support.findings import make_finding

from vibesensor.analysis.diagnosis import build_diagnosis
from vibesensor.domain.finding import Finding
from vibesensor.domain.finding_evidence import FindingEvidence
from vibesensor.domain.finding_types import VibrationSource
from vibesensor.domain.order_match import OrderMatchObservation
from vibesensor.domain.run_capture import RunCapture
from vibesensor.domain.test_run import TestRun
from vibesensor.recording.run_metadata import run_metadata_from_mapping

SENSORS = ["front-left", "front-right", "rear-left", "rear-right"]


def _points(
    location: str, amp_g: float, *, speeds: tuple[float, ...] = (80.0,) * 6
) -> list[OrderMatchObservation]:
    return [
        OrderMatchObservation(
            predicted_hz=wheel_hz(speed),
            matched_hz=wheel_hz(speed),
            rel_error=0.0,
            amp=amp_g,
            location=location,
            speed_kmh=speed,
        )
        for speed in speeds
    ]


def _order_finding(
    key: str,
    source: VibrationSource,
    *,
    confidence: float,
    amps: dict[str, float],
    strength_db: float = 30.0,
    weak_spatial: bool = False,
) -> Finding:
    points = [point for location, amp in amps.items() for point in _points(location, amp)]
    return make_finding(
        finding_id="F001",
        finding_key=key,
        suspected_source=source,
        confidence=confidence,
        strongest_location=max(amps, key=lambda location: amps[location]),
        strongest_speed_band="80-90 km/h",
        vibration_strength_db=strength_db,
        weak_spatial_separation=weak_spatial,
        matched_points=tuple(points),
        evidence=FindingEvidence(match_rate=0.9),
    )


def _diagnosis(*findings: Finding, metadata: dict[str, Any] | None = None) -> Any:
    test_run = TestRun(
        capture=RunCapture(run_id="run-1"),
        findings=findings,
        top_causes=findings,
    )
    return build_diagnosis(
        test_run=test_run,
        samples=[],
        metadata=run_metadata_from_mapping(
            {"run_id": "run-1", **(metadata or standard_metadata())}
        ),
        sensor_count=4,
    )


def test_clear_wheel_fault_names_corner_order_and_mg_per_location() -> None:
    summary = run_analysis(make_fault_samples(fault_sensor="front-left", sensors=SENSORS))
    diagnosis = summary["diagnosis"]

    assert diagnosis["verdict"] == "fault"
    assert diagnosis["confidence_level"] in ("strong", "moderate")
    assert diagnosis["source"] == "wheel/tire"
    assert diagnosis["order_code"] == "T1"
    assert diagnosis["zone"] == "front_left_wheel"
    assert diagnosis["frequency_hz"] == pytest.approx(wheel_hz(80.0), rel=0.02)
    assert diagnosis["amplitude_basis"] == "order"
    rows = diagnosis["location_amplitudes"]
    assert rows[0]["location"] == "front-left"
    assert rows[0]["amplitude_mg"] == pytest.approx(60.0)
    assert rows[0]["ratio_to_strongest"] == 1.0
    assert all(row["ratio_to_strongest"] < 0.5 for row in rows[1:])
    worksheet = diagnosis["order_findings"]
    assert [row["order_code"] for row in worksheet][:1] == ["T1"]
    assert worksheet[0]["finding_id"] == diagnosis["finding_id"]
    assert worksheet[0]["frequency_hz"] == pytest.approx(diagnosis["frequency_hz"])
    checks = {check["source"]: check for check in diagnosis["source_checks"]}
    assert checks["wheel/tire"]["status"] == "candidate"
    assert checks["driveline"]["status"] == "ruled_out"
    # Every finding carries the same single confidence expression.
    assert summary["top_causes"][0]["confidence_level"] == diagnosis["confidence_level"]
    assert "confidence_pct" not in summary["top_causes"][0]


def test_speed_sweep_carries_amplitude_vs_speed_and_speed_range() -> None:
    summary = run_analysis(
        make_speed_sweep_fault_samples(fault_sensor="rear-right", sensors=SENSORS)
    )
    diagnosis = summary["diagnosis"]

    assert diagnosis["zone"] == "rear_right_wheel"
    assert diagnosis["speed_max_kmh"] - diagnosis["speed_min_kmh"] >= 30.0
    speeds = {point["speed_kmh"] for point in diagnosis["amplitude_vs_speed"]}
    assert len(speeds) >= 3
    reference = diagnosis["reference_speed_kmh"]
    assert diagnosis["frequency_hz"] == pytest.approx(wheel_hz(reference), rel=0.03)


def test_engine_order_points_to_the_engine_bay_not_a_corner() -> None:
    summary = run_analysis(make_engine_order_samples(sensors=SENSORS))
    diagnosis = summary["diagnosis"]

    assert diagnosis["source"] == "engine"
    assert diagnosis["zone"] == "engine_bay"
    assert diagnosis["order_code"] in ("E1", "E2")


def test_no_candidate_is_no_fault_with_overall_levels() -> None:
    noise = make_finding(
        finding_id="F001",
        finding_key="peak_7hz",
        suspected_source=VibrationSource.BASELINE_NOISE,
        confidence=0.06,
    )
    diagnosis = _diagnosis(noise)

    assert diagnosis["verdict"] == "no_fault"
    assert diagnosis["confidence_level"] is None
    assert diagnosis["source"] is None
    assert diagnosis["amplitude_basis"] == "overall"


def test_weak_candidate_is_hedged_with_plain_reasons() -> None:
    finding = _order_finding(
        "wheel_1x",
        VibrationSource.WHEEL_TIRE,
        confidence=0.32,
        amps={"Front Left Wheel": 0.030, "Front Right Wheel": 0.027},
        weak_spatial=True,
    )
    diagnosis = _diagnosis(finding)

    assert diagnosis["verdict"] == "weak_evidence"
    assert diagnosis["confidence_level"] == "weak"
    assert diagnosis["source"] == "wheel/tire"
    assert diagnosis["zone"] == "front_axle"
    assert diagnosis["weak_reasons"] == ["spread_across_locations", "narrow_speed_range"]


def test_faint_weak_candidate_is_not_a_significant_vibration() -> None:
    finding = _order_finding(
        "wheel_2x",
        VibrationSource.WHEEL_TIRE,
        confidence=0.30,
        amps={"Rear Left Wheel": 0.004},
        strength_db=9.0,
    )
    diagnosis = _diagnosis(finding)

    assert diagnosis["verdict"] == "no_fault"
    assert diagnosis["source"] is None


def test_wheel_tone_spread_over_most_corners_is_all_wheels() -> None:
    finding = _order_finding(
        "wheel_1x",
        VibrationSource.WHEEL_TIRE,
        confidence=0.32,
        amps={"Front Left Wheel": 0.03, "Front Right Wheel": 0.028, "Rear Left Wheel": 0.025},
        weak_spatial=True,
    )
    diagnosis = _diagnosis(finding)

    assert diagnosis["zone"] == "all_wheels"
    assert [row["order_code"] for row in diagnosis["order_findings"]] == ["T1"]


def test_moderate_candidate_is_a_fault() -> None:
    finding = _order_finding(
        "wheel_1x",
        VibrationSource.WHEEL_TIRE,
        confidence=0.55,
        amps={"Rear Right Wheel": 0.2, "Rear Left Wheel": 0.02},
    )
    diagnosis = _diagnosis(finding)

    assert diagnosis["verdict"] == "fault"
    assert diagnosis["confidence_level"] == "moderate"
    assert diagnosis["zone"] == "rear_right_wheel"
    assert diagnosis["location_amplitudes"][0]["amplitude_mg"] == pytest.approx(200.0)


@pytest.mark.parametrize(
    ("amps", "zone"),
    [
        (
            {"Rear Left Wheel": 0.15, "Rear Right Wheel": 0.145, "Front Left Wheel": 0.04},
            "rear_axle",
        ),
        ({"Driveshaft Tunnel": 0.2, "Rear Left Wheel": 0.05}, "driveshaft_tunnel"),
        ({"Front Left Wheel": 0.1, "Rear Right Wheel": 0.1}, "driveshaft_tunnel"),
    ],
)
def test_driveline_is_reported_as_a_zone(amps: dict[str, float], zone: str) -> None:
    finding = _order_finding("driveshaft_1x", VibrationSource.DRIVELINE, confidence=0.6, amps=amps)
    diagnosis = _diagnosis(finding)

    assert diagnosis["order_code"] == "P1"
    assert diagnosis["zone"] == zone


def test_missing_tire_reference_marks_sources_not_testable() -> None:
    noise = make_finding(
        finding_id="F001",
        finding_key="peak_7hz",
        suspected_source=VibrationSource.BASELINE_NOISE,
        confidence=0.06,
    )
    metadata = {"raw_sample_rate_hz": 800.0, "sensor_model": "ADXL345", "language": "en"}
    diagnosis = _diagnosis(noise, metadata=metadata)

    statuses = {
        check["source"]: (check["status"], check["reason"]) for check in diagnosis["source_checks"]
    }
    assert statuses["wheel/tire"] == ("not_testable", "no_tire_reference")
    assert diagnosis["conditions"]["tire_circumference_m"] is None
