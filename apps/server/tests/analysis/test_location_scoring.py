"""Which sensor location an order finding points at (``summarize_order_match_locations``).

Edge cases the simulator benchmark does not reach: a cabin sensor reading the
wheel order louder than the wheel sensor, two corners within a near tie, and
the sensors that do not hear an order-tracked line.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_support.analysis import summarize_mappings
from test_support.core import (
    ALL_WHEEL_SENSORS,
    assert_summary_sections,
    assert_top_cause_contract,
    standard_metadata,
    wheel_hz,
)
from test_support.synthetic_samples import make_sample

from vibesensor.analysis.location_analysis import summarize_order_match_locations
from vibesensor.analysis.orders.matching import OrderMatchAccumulator
from vibesensor.analysis.orders.physics import _order_hypotheses
from vibesensor.analysis.orders.scoring import (
    OrderFindingBuildContext,
    OrderFindingScore,
    score_order_finding,
)
from vibesensor.domain.locations import is_wheel_location
from vibesensor.domain.order_match import OrderMatchObservation, SensorOrderLevel


def _obs(
    speed_kmh: float, amp: float, location: str, rel_error: float = 0.0
) -> OrderMatchObservation:
    return OrderMatchObservation(
        predicted_hz=10.0,
        matched_hz=10.0,
        rel_error=rel_error,
        amp=amp,
        location=location,
        speed_kmh=speed_kmh,
    )


def test_wheel_order_points_at_the_wheel_sensor_even_when_a_seat_reads_louder() -> None:
    matches = [
        obs
        for i in range(20)
        for obs in (
            _obs(60.0 + 2 * i, 0.08, "Driver Seat", rel_error=0.02),
            _obs(60.0 + 2 * i, 0.06, "Front Left", rel_error=0.01),
        )
    ]

    _, result = summarize_order_match_locations(matches, lang="en", suspected_source="wheel/tire")

    assert result is not None
    assert is_wheel_location(result.top_location), result.top_location


def test_near_tie_between_two_corners_is_reported_as_ambiguous() -> None:
    matches = [
        _obs(85.0, 0.0110, "Rear Right"),
        _obs(85.0, 0.0102, "Rear Left"),
        _obs(86.0, 0.0112, "Rear Right"),
        _obs(86.0, 0.0103, "Rear Left"),
    ]

    sentence, result = summarize_order_match_locations(matches, lang="en")

    assert result is not None
    assert result.ambiguous_location
    assert result.display_location == "ambiguous location: Rear Right / Rear Left"
    assert list(result.hotspot.alternative_locations) == ["Rear Right", "Rear Left"]
    assert result.localization_confidence < 0.4
    assert isinstance(sentence, dict)
    assert "ambiguous location" in str(sentence.get("location", ""))


def test_a_wheel_sensor_that_drops_out_and_rejoins_does_not_move_the_fault() -> None:
    samples: list[dict[str, Any]] = []
    whz = wheel_hz(80.0)
    for i in range(40):
        for sensor in ALL_WHEEL_SENSORS:
            if sensor == "rear-left" and 10 <= i < 20:
                continue
            if sensor == "front-right":
                peaks = [{"hz": whz, "amp": 0.06}, {"hz": whz * 2, "amp": 0.024}]
                vib_db = 26.0
            else:
                peaks = [{"hz": 142.5, "amp": 0.003}]
                vib_db = 8.0
            samples.append(
                make_sample(
                    t_s=float(i),
                    speed_kmh=80.0,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=vib_db,
                    strength_floor_amp_g=0.003,
                ),
            )
    summary = summarize_mappings(
        standard_metadata(),
        samples,
        lang="en",
        file_name="rejoin_test",
    )
    assert_summary_sections(summary, min_top_causes=1)
    assert_top_cause_contract(
        summary["top_causes"][0],
        expected_source="wheel",
        expected_location="front-right",
    )


# Order-tracked levels (``SensorOrderLevel``): a sensor whose reads do not
# stand out of their scatter reads 0, its read is kept beside it.
_WHEELS = ("Front Left Wheel", "Front Right Wheel", "Rear Left Wheel", "Rear Right Wheel")


def _tracked_score(
    hypothesis_key: str,
    matched_at: tuple[str, ...],
    levels: dict[str, tuple[float, float]],
    heard_locations: tuple[str, ...],
) -> OrderFindingScore:
    """Score an order matched 20 times at each of *matched_at*, tracked at *levels*.

    *levels*: location -> (level, read) in g, every sensor's floor 30 mg.
    """
    points = [
        OrderMatchObservation(
            predicted_hz=30.0 + window,
            matched_hz=30.0 + window,
            rel_error=0.0,
            amp=0.04,
            location=location,
            t_s=float(window),
            speed_kmh=95.0 + 0.2 * window,
            heard=location in heard_locations,
        )
        for location in matched_at
        for window in range(20)
    ]
    match = OrderMatchAccumulator(
        possible=20 * len(levels),
        matched_points=points,
        matched_floor=[0.004] * len(points),
        ref_sources={"speed+tire"},
        possible_by_speed_bin={},
        matched_by_speed_bin={},
        possible_by_phase={},
        matched_by_phase={},
        possible_by_location=dict.fromkeys(levels, 20),
        matched_by_location=dict.fromkeys(matched_at, 20),
        has_phases=False,
        compliance=1.0,
        heard_locations=frozenset(heard_locations),
        corroboration=float(len(heard_locations)),
        sensor_levels=tuple(
            SensorOrderLevel(location, level, 0.03, windows=20, read_g=read)
            for location, (level, read) in levels.items()
        ),
    )
    context = OrderFindingBuildContext(
        effective_match_rate=1.0,
        focused_speed_band=None,
        per_location_dominant=False,
        match_rate=1.0,
        min_match_rate=0.25,
        constancy=0.0,
        steadiness=0.0,
        connected_locations=set(levels),
        lang="en",
    )
    hypothesis = next(h for h in _order_hypotheses() if h.key == hypothesis_key)
    return score_order_finding(hypothesis, match, context=context)


def test_a_wheel_order_no_wheel_sensor_hears_is_not_put_at_a_wheel_by_its_floor_reads() -> None:
    # An engine order on a wheel order's line in top gear, heard at the trunk
    # alone: under the wheel-hop hump the wheel sensors' reads are the floor's
    # scatter, louder than the trunk's level, and hear nothing.
    score = _tracked_score(
        "wheel_2x",
        ("Trunk", *_WHEELS),
        {
            "Trunk": (0.006, 0.006),
            **dict(
                zip(_WHEELS, ((0.0, 0.019), (0.0, 0.017), (0.0, 0.012), (0.0, 0.0)), strict=True)
            ),
        },
        heard_locations=("Trunk",),
    )

    assert score.strongest_location == "Trunk"
    assert score.weak_spatial_separation


def test_an_order_heard_at_one_sensor_alone_is_located_there() -> None:
    # The sensors that do not hear it are quieter, matched or not.
    score = _tracked_score(
        "engine_2x",
        ("Trunk",),
        {"Trunk": (0.025, 0.025), **{wheel: (0.0, 0.005) for wheel in _WHEELS}},
        heard_locations=("Trunk",),
    )

    assert score.strongest_location == "Trunk"
    assert not score.weak_spatial_separation
    assert score.dominance_ratio is not None and score.dominance_ratio > 2.0


def test_a_sensor_that_hears_an_order_under_the_wheel_hop_is_placed_by_its_read() -> None:
    # Front-left hears the wheel order (its matches stand clear of the
    # window's floor) though its line reads do not stand out of the hump's
    # scatter; the trunk's do, far quieter. The rear-right's read is as loud,
    # but it does not hear the order.
    score = _tracked_score(
        "wheel_1x",
        ("Trunk", *_WHEELS),
        {
            "Trunk": (0.033, 0.033),
            "Front Left Wheel": (0.0, 0.211),
            "Front Right Wheel": (0.0, 0.113),
            "Rear Left Wheel": (0.0, 0.047),
            "Rear Right Wheel": (0.0, 0.202),
        },
        heard_locations=("Trunk", "Front Left Wheel"),
    )

    assert score.strongest_location == "Front Left Wheel"
    assert not score.weak_spatial_separation


@pytest.mark.parametrize(("rear_wheels_match", "spread"), [(True, True), (False, False)])
def test_quiet_sensors_count_among_the_spread_only_where_they_matched(
    rear_wheels_match: bool, spread: bool
) -> None:
    # Both front wheels hear the order, 1.23x apart; the rear wheels do not.
    # Matched there, they are four wheels the order could be spread over
    # (weak at under 1.44x); unmatched, the two front wheels are compared
    # alone (weak at under 1.2x).
    rear = _WHEELS[2:]
    score = _tracked_score(
        "wheel_1x",
        ("Trunk", *_WHEELS[:2], *(rear if rear_wheels_match else ())),
        {
            "Trunk": (0.0, 0.0025),
            "Front Left Wheel": (0.058, 0.058),
            "Front Right Wheel": (0.047, 0.047),
            **{wheel: (0.0, 0.0023) for wheel in rear},
        },
        heard_locations=("Trunk", *_WHEELS[:2]),
    )

    assert score.strongest_location == "Front Left Wheel"
    assert score.weak_spatial_separation is spread
