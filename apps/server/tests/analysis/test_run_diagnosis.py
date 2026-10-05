"""The persisted diagnosis block: verdict, confidence level, order label, mg amplitudes, zone."""

from __future__ import annotations

from typing import Any

import pytest
from test_support.analysis import run_analysis
from test_support.core import engine_hz, standard_metadata, wheel_hz
from test_support.findings import make_finding
from test_support.synthetic_samples import make_engine_order_samples

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
            t_s=float(index),
            speed_kmh=speed,
        )
        for index, speed in enumerate(speeds)
    ]


def _order_finding(
    key: str,
    source: VibrationSource,
    *,
    confidence: float,
    amps: dict[str, float],
    strength_db: float = 30.0,
    weak_spatial: bool = False,
    finding_id: str = "F001",
) -> Finding:
    points = [point for location, amp in amps.items() for point in _points(location, amp)]
    return make_finding(
        finding_id=finding_id,
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


@pytest.mark.parametrize(
    ("amps", "weak_spatial", "zone"),
    [
        # A cabin sensor close behind the only wheel sensor: that corner, not its axle.
        ({"Front Left Wheel": 0.15, "Driver Seat": 0.12}, True, "front_left_wheel"),
        ({"Driver Seat": 0.16, "Front Left Wheel": 0.15}, True, "front_left_wheel"),
        (
            {"Front Left Wheel": 0.15, "Front Right Wheel": 0.14, "Driver Seat": 0.12},
            True,
            "front_axle",
        ),
        # A corner the order analysis found clearly dominant names the zone, even
        # when the medians over the whole drive put another corner close to it
        # (a fault that was there for only part of the drive).
        ({"Front Left Wheel": 0.15, "Front Right Wheel": 0.14}, False, "front_left_wheel"),
    ],
)
def test_wheel_zone_needs_two_corners_for_an_axle(
    amps: dict[str, float], weak_spatial: bool, zone: str
) -> None:
    finding = _order_finding(
        "wheel_1x",
        VibrationSource.WHEEL_TIRE,
        confidence=0.6,
        amps=amps,
        weak_spatial=weak_spatial,
    )

    assert _diagnosis(finding)["zone"] == zone


# -- guided test drive: neutral coast-down -------------------------------------

_COAST_START_S = 28.0
_GUIDED = [
    {"phase": "sweep", "start_t_s": 0.0, "end_t_s": 14.0},
    {"phase": "hold", "start_t_s": 14.0, "end_t_s": _COAST_START_S},
    {"phase": "coast_down", "start_t_s": _COAST_START_S, "end_t_s": 40.0},
]


def _guided_analysis(
    samples: list[dict[str, Any]], *, stops_in_neutral: bool, neutral_peaks: list[dict] = ()
) -> Any:
    if stops_in_neutral:
        for sample in samples:
            if sample["t_s"] >= _COAST_START_S:
                sample["top_peaks"] = [*neutral_peaks, {"hz": 200.0, "amp": 0.004}]
                sample["vibration_strength_db"] = 8.0
    return run_analysis(samples, standard_metadata(guided_phases=_GUIDED))["diagnosis"]


# Once the engine tone is gone, road noise at the floor (0.004 g) may still sit
# on its predicted frequency: a match, but no vibration.
@pytest.mark.parametrize(
    "neutral_peaks",
    [(), ({"hz": engine_hz(80.0), "amp": 0.004},)],
    ids=["silent", "floor-noise-on-the-engine-order"],
)
def test_engine_tone_that_stops_in_neutral_follows_engine_speed(neutral_peaks: tuple) -> None:
    diagnosis = _guided_analysis(
        make_engine_order_samples(sensors=SENSORS, n_samples=40),
        stops_in_neutral=True,
        neutral_peaks=list(neutral_peaks),
    )

    assert diagnosis["source"] == "engine"
    assert diagnosis["speed_dependence"] == "engine_speed"
    assert "coast_test_contradicts" not in diagnosis["weak_reasons"]
    checks = {check["source"]: check for check in diagnosis["source_checks"]}
    assert checks["wheel/tire"]["reason"] == "stopped_in_neutral"
