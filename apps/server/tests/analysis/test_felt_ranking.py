"""Felt ranking: causes ranked by their order level at the sensor nearest the occupants.

The benchmark checks the ranking end to end from what the simulator injects at
the cabin sensors; these cover the combination rules it cannot isolate.
"""

from __future__ import annotations

import pytest
from test_support.findings import make_finding

from vibesensor.analysis.felt_ranking import FeltAttribution, felt_ranking, rank_by_felt
from vibesensor.domain.finding import Finding
from vibesensor.domain.finding_types import VibrationSource
from vibesensor.domain.order_match import OrderMatchObservation, SensorOrderLevel
from vibesensor.dsp.window_spectrum import tone_line_level_g

_BIN_HZ = 800 / 2048


def _cause(
    finding_id: str,
    source: str,
    key: str,
    levels: dict[str, float],
    *,
    confidence: float = 0.75,
    speeds: tuple[float, float] = (60.0, 120.0),
) -> Finding:
    points = tuple(
        OrderMatchObservation(
            predicted_hz=10.0,
            matched_hz=10.0,
            rel_error=0.0,
            amp=0.01,
            location="x",
            speed_kmh=speed,
            heard=True,
        )
        for speed in speeds
    )
    return make_finding(
        finding_id,
        source,
        confidence=confidence,
        finding_key=key,
        matched_points=points,
        sensor_levels=tuple(
            SensorOrderLevel(location=location, level_g=level, floor_g=0.0001, windows=40)
            for location, level in levels.items()
        ),
    )


def test_the_cause_the_trunk_feels_most_ranks_first() -> None:
    wheel = _cause("W", "wheel/tire", "wheel_1x", {"Front Left Wheel": 0.2, "Trunk": 0.0})
    shaft = _cause(
        "P",
        "driveline",
        "driveshaft_1x",
        {"Rear Left Wheel": 0.1, "Trunk": 0.02},
        confidence=0.5,
    )

    ranked = rank_by_felt((wheel, shaft), (wheel, shaft))

    assert [f.finding_id for f in ranked] == ["P", "W"]


def test_a_seat_is_the_reference_before_the_trunk() -> None:
    wheel = _cause("W", "wheel/tire", "wheel_1x", {"Trunk": 0.03, "Driver Seat": 0.01})

    assert felt_ranking((wheel,), (wheel,)).reference == "Driver Seat"


@pytest.mark.parametrize(
    ("levels", "fallback"),
    [
        ({"Front Left Wheel": 0.2, "Engine Bay": 0.05}, "no_cabin_sensor"),
        ({}, "no_order_levels"),
    ],
)
def test_without_a_felt_reference_the_ranking_by_evidence_stays(
    levels: dict[str, float], fallback: str
) -> None:
    wheel = _cause("W", "wheel/tire", "wheel_1x", levels)
    engine = _cause("E", "engine", "engine_2x", {}, confidence=0.5)

    ranking = felt_ranking((wheel, engine), (wheel, engine))

    assert ranking.reference is None and ranking.fallback == fallback
    assert rank_by_felt((wheel, engine), (wheel, engine)) == (wheel, engine)


def test_a_weak_cause_never_outranks_a_moderate_one() -> None:
    wheel = _cause("W", "wheel/tire", "wheel_1x", {"Trunk": 0.001})
    engine = _cause("E", "engine", "engine_2x", {"Trunk": 0.05}, confidence=0.3)

    assert [f.finding_id for f in rank_by_felt((wheel, engine), (wheel, engine))] == ["W", "E"]


def test_a_sources_orders_add_in_power_and_a_shared_line_counts_once() -> None:
    # T1 30 mg and T2 40 mg make the wheels 50 mg at the trunk; a second corner's
    # T1 is the same line there. The engine's 50 mg shares the same speeds.
    t1 = _cause("T1", "wheel/tire", "wheel_1x", {"Trunk": 0.03})
    t2 = _cause("T2", "wheel/tire", "wheel_2x", {"Trunk": 0.04})
    other_corner = _cause("T1B", "wheel/tire", "wheel_1x", {"Trunk": 0.03})
    engine = _cause("E", "engine", "engine_2x", {"Trunk": 0.05})
    findings = (t1, t2, other_corner, engine)

    causes = felt_ranking((t1, engine), findings).causes

    assert [c.level_g for c in causes] == pytest.approx([0.05, 0.05])
    assert [c.share for c in causes] == pytest.approx([0.5, 0.5])


def test_a_source_the_diagnosis_rules_out_is_no_felt_cause() -> None:
    wheel = _cause("W", "wheel/tire", "wheel_1x", {"Trunk": 0.05})
    engine = _cause("E", "engine", "engine_1x", {"Trunk": 0.03})
    coast_down = FeltAttribution(ruled_out=frozenset({VibrationSource.WHEEL_TIRE}))

    (felt,) = felt_ranking((wheel, engine), (wheel, engine), coast_down).causes

    assert felt.finding is engine and felt.share == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("owner", "expected"),
    [
        # The wheels named: the shared line is their T2; the engine keeps its E2.
        (VibrationSource.WHEEL_TIRE, {"W": ("T1", "T2"), "E": ("E2",)}),
        (VibrationSource.ENGINE, {"E": ("E1", "E2"), "W": ("T1",)}),
    ],
)
def test_an_engine_order_on_a_wheel_orders_line_counts_once_for_the_diagnosed_source(
    owner: VibrationSource, expected: dict[str, tuple[str, ...]]
) -> None:
    # Without measured RPM, E1 turns with T2 in top gear: one line at the trunk.
    t1 = _cause("W", "wheel/tire", "wheel_1x", {"Trunk": 0.03})
    t2 = _cause("T2", "wheel/tire", "wheel_2x", {"Trunk": 0.04})
    e1 = _cause("E", "engine", "engine_1x", {"Trunk": 0.04})
    e2 = _cause("E2", "engine", "engine_2x", {"Trunk": 0.02})
    attribution = FeltAttribution(line_of={"E1": "T2"}, owner=owner)

    causes = felt_ranking((t1, e1), (t1, t2, e1, e2), attribution).causes

    assert {c.finding.finding_id: tuple(code for code, _ in c.order_levels_g) for c in causes} == (
        expected
    )
    # T1, T2 (= E1) and E2: 9 + 16 + 4 in power, each line once.
    assert sum(c.share or 0.0 for c in causes) == pytest.approx(1.0)


def test_a_cause_whose_only_line_is_the_diagnosed_sources_is_not_listed() -> None:
    t2 = _cause("W", "wheel/tire", "wheel_2x", {"Trunk": 0.04})
    e1 = _cause("E", "engine", "engine_1x", {"Trunk": 0.04})
    attribution = FeltAttribution(line_of={"E1": "T2"}, owner=VibrationSource.WHEEL_TIRE)

    (felt,) = felt_ranking((e1, t2), (t2, e1), attribution).causes

    assert felt.finding is t2 and felt.share == pytest.approx(1.0)


def test_causes_heard_at_different_speeds_each_explain_their_own() -> None:
    wheel = _cause("W", "wheel/tire", "wheel_1x", {"Trunk": 0.03}, speeds=(90.0, 120.0))
    engine = _cause("E", "engine", "engine_2x", {"Trunk": 0.01}, speeds=(30.0, 50.0))

    causes = felt_ranking((wheel, engine), (wheel, engine)).causes

    assert [c.share for c in causes] == pytest.approx([1.0, 1.0])


@pytest.mark.parametrize(
    ("source", "key", "peak_g", "severity"),
    [
        ("wheel/tire", "wheel_1x", 0.030, "workshop"),
        ("wheel/tire", "wheel_1x", 0.020, "below_workshop"),
        ("engine", "engine_2x", 0.015, "workshop"),
        ("engine", "engine_2x", 0.006, "below_workshop"),
        ("engine", "engine_2x", 0.0015, "normal"),
    ],
)
def test_severity_compares_the_level_with_the_seat_track_limit_on_one_axis(
    source: str, key: str, peak_g: float, severity: str
) -> None:
    # A tone at *peak_g* on one axis: the GM limits are 25 mg (wheels) and
    # 12 mg (engine; 2 mg or less normal) on one axis of the seat track.
    cause = _cause("C", source, key, {"Driver Seat": tone_line_level_g(peak_g, _BIN_HZ)})

    (felt,) = felt_ranking((cause,), (cause,)).causes

    assert felt.severity(_BIN_HZ) == severity


def test_a_cause_the_reference_does_not_measure_has_no_share_or_severity() -> None:
    wheel = _cause("W", "wheel/tire", "wheel_1x", {"Front Left Wheel": 0.2, "Trunk": 0.0})

    (felt,) = felt_ranking((wheel,), (wheel,)).causes

    assert felt.share is None and felt.severity(_BIN_HZ) is None


def test_a_level_below_the_floor_beside_its_line_is_not_felt() -> None:
    # A body mode the line sweeps over reads as a level under the floor around it.
    wheel = _cause("W", "wheel/tire", "wheel_1x", {"Trunk": 0.00009})

    (felt,) = felt_ranking((wheel,), (wheel,)).causes

    assert felt.level_g == 0.0
