"""The persisted diagnosis block: verdict, confidence level, order label, mg amplitudes, zone."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from test_support.analysis import run_analysis
from test_support.core import engine_hz, standard_metadata, wheel_hz
from test_support.findings import make_finding
from test_support.synthetic_samples import make_engine_order_samples, make_sample

from vibesensor.analysis.diagnosis import build_diagnosis
from vibesensor.analysis.orders.tracking import window_duration_s
from vibesensor.domain.finding import Finding
from vibesensor.domain.finding_evidence import FindingEvidence
from vibesensor.domain.finding_types import VibrationSource
from vibesensor.domain.order_match import OrderMatchObservation, SensorOrderLevel
from vibesensor.domain.run_capture import RunCapture
from vibesensor.domain.test_run import TestRun
from vibesensor.dsp.vibration_strength import vibration_strength_db_scalar
from vibesensor.dsp.window_spectrum import tone_line_level_g
from vibesensor.recording.run_metadata import run_metadata_from_mapping
from vibesensor.recording.sensor_frame_mapping import sensor_frame_from_mapping

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
        # The only wheel sensor feels every wheel's imbalance: no corner is named,
        # whether it reads strongest or a cabin sensor does (then where it was felt).
        ({"Front Left Wheel": 0.15}, True, None),
        ({"Front Left Wheel": 0.15, "Driver Seat": 0.12}, True, None),
        ({"Driver Seat": 0.16, "Front Left Wheel": 0.15}, True, "driver_seat"),
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
    amps: dict[str, float], weak_spatial: bool, zone: str | None
) -> None:
    finding = _order_finding(
        "wheel_1x",
        VibrationSource.WHEEL_TIRE,
        confidence=0.6,
        amps=amps,
        weak_spatial=weak_spatial,
    )

    assert _diagnosis(finding)["zone"] == zone


def test_amplitudes_are_shown_as_the_peak_of_the_tone_that_reads_them() -> None:
    """Every mg is on the scale workshop limits are on: the level a 30 mg tone
    reads on the combined spectrum shows as 30 mg."""
    metadata = run_metadata_from_mapping({"run_id": "run-1", **standard_metadata()})
    level_g = tone_line_level_g(0.030, 1.0 / window_duration_s(metadata))
    finding = _order_finding(
        "wheel_1x", VibrationSource.WHEEL_TIRE, confidence=0.6, amps={"Front Left Wheel": level_g}
    )
    diagnosis = _diagnosis(finding)

    assert diagnosis["location_amplitudes"][0]["amplitude_mg"] == pytest.approx(30.0)
    assert [point["amplitude_mg"] for point in diagnosis["amplitude_vs_speed"]] == [
        pytest.approx(30.0)
    ]


def test_an_order_rows_db_is_over_its_locations_floor_as_every_other_db() -> None:
    """The bracketed dB has one meaning: over the location's spectrum floor, as
    a no-fault run's rows and the live view give it, not over the floor beside
    the order's line (a wheel imbalance on a road's wheel hop read 6 dB there,
    34 dB live, while a healthy wheel's row read 40 dB)."""
    finding = _order_finding(
        "wheel_1x", VibrationSource.WHEEL_TIRE, confidence=0.6, amps={"front-left": 0.1}
    )
    finding = replace(
        finding,
        sensor_levels=(SensorOrderLevel("front-left", level_g=0.1, floor_g=0.05, windows=40),),
    )
    metadata = run_metadata_from_mapping({"run_id": "run-1", **standard_metadata()})
    samples = [
        sensor_frame_from_mapping(
            make_sample(
                t_s=float(index),
                speed_kmh=80.0,
                client_name="front-left",
                strength_floor_amp_g=floor_g,
            )
        )
        for index, floor_g in enumerate((0.001, 0.002, 0.004))
    ]
    diagnosis = build_diagnosis(
        test_run=TestRun(
            capture=RunCapture(run_id="run-1"), findings=(finding,), top_causes=(finding,)
        ),
        samples=samples,
        metadata=metadata,
        sensor_count=1,
    )

    (row,) = diagnosis["location_amplitudes"]
    assert row["db_above_floor"] == pytest.approx(
        vibration_strength_db_scalar(peak_band_rms_amp_g=0.1, floor_amp_g=0.002)
    )


@pytest.mark.parametrize(
    ("diagnosed_amp", "first"),
    [
        # Within location scoring's near tie the diagnosis's location leads.
        (0.160, "Front Right Wheel"),
        # Clearly weaker, it does not.
        (0.140, "Rear Right Wheel"),
    ],
)
def test_the_amplitude_rows_lead_with_the_diagnosed_location_on_a_near_tie(
    diagnosed_amp: float, first: str
) -> None:
    finding = _order_finding(
        "wheel_1x",
        VibrationSource.WHEEL_TIRE,
        confidence=0.6,
        amps={"Rear Right Wheel": 0.171, "Front Right Wheel": diagnosed_amp, "Driver Seat": 0.05},
    )
    diagnosis = _diagnosis(replace(finding, strongest_location="Front Right Wheel"))

    assert diagnosis["location"] == "Front Right Wheel"
    assert [row["location"] for row in diagnosis["location_amplitudes"]][0] == first
    assert max(row["ratio_to_strongest"] for row in diagnosis["location_amplitudes"]) == 1.0


@pytest.mark.parametrize("source", [VibrationSource.WHEEL_TIRE, VibrationSource.BRAKES])
@pytest.mark.parametrize("weak_spatial", [True, False])
def test_one_sensor_is_always_said_and_caps_a_corner_fault_at_moderate(
    source: VibrationSource, weak_spatial: bool
) -> None:
    """One sensor compares no locations: it names no corner or axle, says so
    first, calls nothing "spread across locations" and is never Strong."""
    finding = _order_finding(
        "wheel_1x",
        source,
        confidence=0.95,
        amps={"Front Left Wheel": 0.15},
        weak_spatial=weak_spatial,
    )
    test_run = TestRun(
        capture=RunCapture(run_id="run-1"), findings=(finding,), top_causes=(finding,)
    )
    diagnosis = build_diagnosis(
        test_run=test_run,
        samples=[],
        metadata=run_metadata_from_mapping({"run_id": "run-1", **standard_metadata()}),
        sensor_count=1,
    )

    assert diagnosis["zone"] is None
    assert diagnosis["confidence_level"] == "moderate"
    assert diagnosis["weak_reasons"] == ["single_sensor", "narrow_speed_range"]


def test_the_frequency_is_stated_in_the_gear_of_the_strongest_speed_band() -> None:
    """An engine order heard through the gears runs at another Hz per km/h in
    each: its frequency is stated at the strongest band's speed in that band's
    gear, not in the gear most of the drive was in."""
    third = [(35.0 + index * 0.5, 1.6) for index in range(6)]
    fifth = [(95.0 + index, 1.0) for index in range(10)]
    points = tuple(
        OrderMatchObservation(
            predicted_hz=speed * hz_per_kmh,
            matched_hz=speed * hz_per_kmh,
            rel_error=0.0,
            amp=0.1,
            location="Front Left Wheel",
            t_s=float(index),
            speed_kmh=speed,
        )
        for index, (speed, hz_per_kmh) in enumerate(third + fifth)
    )
    finding = make_finding(
        finding_id="F001",
        finding_key="engine_1x",
        suspected_source=VibrationSource.ENGINE,
        confidence=0.6,
        strongest_location="Front Left Wheel",
        strongest_speed_band="30-40 km/h",
        vibration_strength_db=30.0,
        matched_points=points,
        evidence=FindingEvidence(match_rate=0.9),
    )

    diagnosis = _diagnosis(finding)

    assert diagnosis["frequency_hz"] == pytest.approx(1.6 * diagnosis["reference_speed_kmh"])
    assert 30.0 <= diagnosis["reference_speed_kmh"] < 40.0


def test_a_no_fault_run_lists_no_order_it_found_only_faintly() -> None:
    """A faint wheel order felt evenly at every corner is a healthy car's residual
    imbalance: the run reads as no fault, so it is not listed as a Moderate
    worksheet row or a candidate; the wheels are ruled out as found only faintly."""
    amps = {
        "Front Left Wheel": 0.02,
        "Front Right Wheel": 0.019,
        "Rear Left Wheel": 0.02,
        "Rear Right Wheel": 0.019,
    }
    faint = _order_finding(
        "wheel_1x",
        VibrationSource.WHEEL_TIRE,
        confidence=0.6,
        amps=amps,
        strength_db=12.0,
        weak_spatial=True,
    )

    diagnosis = _diagnosis(faint)

    assert diagnosis["verdict"] == "no_fault"
    assert diagnosis["order_findings"] == []
    checks = {
        check["source"]: (check["status"], check["reason"]) for check in diagnosis["source_checks"]
    }
    assert checks["wheel/tire"] == ("ruled_out", "faint_only")


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
    for sample in samples:
        if sample["t_s"] >= _COAST_START_S:
            # The coast-down really coasts: the car sheds speed off the brakes.
            sample["speed_kmh"] -= 2.0 * (sample["t_s"] - _COAST_START_S)
            if stops_in_neutral:
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


def test_the_coast_down_is_judged_where_the_order_is_heard() -> None:
    # A trunk sensor that does not hear the engine matches floor-level noise on
    # its frequency in every window, as often as the sensors that hear it. The
    # coast-down is judged at a sensor that hears the order, and the trunk's
    # per-location presence counts none of its floor-level matches.
    samples = []
    engine = make_engine_order_samples(sensors=SENSORS, n_samples=40, engine_amp=0.08)
    for engine_sample in engine:
        if engine_sample["client_name"] == SENSORS[0]:
            samples.append(
                make_sample(
                    t_s=engine_sample["t_s"],
                    speed_kmh=80.0,
                    client_name="trunk",
                    top_peaks=[{"hz": engine_hz(80.0), "amp": 0.004}, {"hz": 200.0, "amp": 0.004}],
                    strength_floor_amp_g=0.004,
                    engine_rpm=engine_hz(80.0) * 60.0,
                )
            )
        samples.append(engine_sample)

    diagnosis = _guided_analysis(samples, stops_in_neutral=True)

    assert diagnosis["source"] == "engine"
    assert diagnosis["speed_dependence"] == "engine_speed"
    presence = {row["location"]: row["presence_ratio"] for row in diagnosis["location_amplitudes"]}
    assert presence["trunk"] == 0.0
    assert presence["front-left"] > 0.5
