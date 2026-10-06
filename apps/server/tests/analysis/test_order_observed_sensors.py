"""The evidence stage: each order match is classified once as heard or not.

A vibration fades with distance from its source, and the matcher, which takes
the nearest peak in the tolerance band, also lands on floor-level road noise
near the predicted frequency at every sensor. Neither may count for or against
an order, in any metric. Hand-placed peaks, because the simulator benchmark
cannot isolate these rules.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from test_support.analysis import run_analysis
from test_support.core import standard_metadata, wheel_hz
from test_support.synthetic_samples import make_sample

from vibesensor.analysis._reference_resolution import ESTIMATED_RPM_SOURCE
from vibesensor.analysis.orders.matching import OrderMatchAccumulator, _sensors_that_hear
from vibesensor.analysis.orders.physics import _order_hypotheses
from vibesensor.analysis.orders.scoring import (
    OrderFindingBuildContext,
    OrderFindingScore,
    score_order_finding,
)
from vibesensor.domain.order_match import OrderMatchObservation

# E1 at 2.72 x T1 in top gear (ratio 0.8): engine orders fall between wheel orders.
_E1_PER_T1 = 2.72
_TOP_GEAR = 0.8
_E2_PER_T1 = 2 * _E1_PER_T1
_FLOOR_G = 0.004
# A peak within 6 dB of the floor: road noise near the predicted frequency.
_NOISE_G = 0.0045
_REAR = ("rear_left_wheel", "rear_right_wheel")

# location -> [(multiple of T1, amplitude g, windows it is present in)]
Tones = dict[str, list[tuple[float, float, Callable[[int], bool]]]]


def _always(_step: int) -> bool:
    return True


def _drive(tones: Tones, *, steps: int = 60) -> list[dict]:
    """Sweep 50-115 km/h in top gear with four wheel sensors and one in the trunk."""
    samples = []
    for step in range(steps):
        speed_kmh = 50.0 + 65.0 * step / (steps - 1)
        t1_hz = wheel_hz(speed_kmh)
        for index, location in enumerate(
            (*_REAR, "front_left_wheel", "front_right_wheel", "trunk")
        ):
            peaks = [{"hz": 142.5, "amp": _FLOOR_G}]
            for multiple, amp_g, present in tones.get(location, []):
                if present(step):
                    jitter = 1.0 + 0.03 * ((step * 7 + index) % 5)
                    peaks.append({"hz": multiple * t1_hz, "amp": amp_g * jitter})
            sample = make_sample(
                t_s=step * 0.5,
                speed_kmh=speed_kmh,
                client_name=location,
                location=location,
                top_peaks=peaks,
                vibration_strength_db=20.0,
                strength_floor_amp_g=_FLOOR_G,
                engine_rpm=_E1_PER_T1 * t1_hz * 60.0,
            )
            sample["engine_rpm_source"] = ESTIMATED_RPM_SOURCE
            samples.append(sample)
    return samples


def _metadata() -> dict:
    return standard_metadata(
        run_id="run-1",
        final_drive_ratio=_E1_PER_T1 / _TOP_GEAR,
        current_gear_ratio=_TOP_GEAR,
    )


def _analyse(tones: Tones) -> dict:
    return run_analysis(_drive(tones), _metadata())


def _engine_finding(summary: dict) -> dict:
    return max(
        (f for f in summary["findings"] if f["suspected_source"] == "engine"),
        key=lambda f: f["confidence"],
    )


def test_sensors_that_do_not_hear_an_order_do_not_dilute_it() -> None:
    # The front sensors and the trunk hear the engine's E2 all the drive. The rear
    # sensors do not: the matcher lands on road noise there every other window,
    # and on a bump clear of the floor every seventh.
    def rear_noise(step: int) -> bool:
        return step % 2 == 0 and step % 7 != 0

    def rear_bump(step: int) -> bool:
        return step % 7 == 0

    heard = 0.05
    summary = _analyse(
        {
            "front_left_wheel": [(_E2_PER_T1, heard, _always)],
            "front_right_wheel": [(_E2_PER_T1, heard, _always)],
            "trunk": [(_E2_PER_T1, 0.6 * heard, _always)],
            **{
                location: [(_E2_PER_T1, _NOISE_G, rear_noise), (_E2_PER_T1, 0.012, rear_bump)]
                for location in _REAR
            },
        }
    )

    metrics = _engine_finding(summary)["evidence_metrics"]
    assert metrics["global_match_rate"] < 0.9
    assert metrics["match_rate"] == pytest.approx(1.0)
    diagnosis = summary["diagnosis"]
    assert (diagnosis["source"], diagnosis["order_code"], diagnosis["confidence_level"]) == (
        "engine",
        "E2",
        "strong",
    )


def test_road_noise_on_an_orders_frequency_does_not_hide_its_clear_presence() -> None:
    # An engine tone both front sensors hear clearly in 70 % of the windows, while
    # road noise sits on its frequency at the three other sensors all the time.
    # Its clear presence is judged where it is heard: the noise is no reason to
    # call the engine-bay zone uncertain.
    def present(step: int) -> bool:
        return step % 10 < 7

    summary = _analyse(
        {
            "front_left_wheel": [(_E2_PER_T1, 0.1, present)],
            "front_right_wheel": [(_E2_PER_T1, 0.1, present)],
            **{location: [(_E2_PER_T1, _NOISE_G, _always)] for location in (*_REAR, "trunk")},
        }
    )

    diagnosis = summary["diagnosis"]
    assert (diagnosis["source"], diagnosis["zone"], diagnosis["confidence_level"]) == (
        "engine",
        "engine_bay",
        "strong",
    )


def _engine_strength_db(tones: Tones) -> float:
    return _engine_finding(_analyse(tones))["evidence_metrics"]["vibration_strength_db"]


def test_sensors_that_do_not_hear_an_order_do_not_dilute_its_strength() -> None:
    # A faint E2 both front sensors hear all the drive. At the three other
    # sensors the matcher lands on road noise at the floor in every window, and
    # on a bump clear of the floor every seventh: neither is the order's level.
    def bump(step: int) -> bool:
        return step % 7 == 0

    def noise(step: int) -> bool:
        return not bump(step)

    heard = {
        location: [(_E2_PER_T1, 0.03, _always)]
        for location in ("front_left_wheel", "front_right_wheel")
    }
    far = {
        location: [(_E2_PER_T1, _NOISE_G, noise), (_E2_PER_T1, 0.012, bump)]
        for location in (*_REAR, "trunk")
    }

    summary = _analyse({**heard, **far})

    finding = _engine_finding(summary)
    assert finding["evidence_metrics"]["vibration_strength_db"] == pytest.approx(
        _engine_strength_db(heard), abs=0.1
    )
    diagnosis = summary["diagnosis"]
    assert (diagnosis["source"], diagnosis["order_code"], diagnosis["confidence_level"]) == (
        "engine",
        "E2",
        "strong",
    )


def test_windows_an_order_is_absent_do_not_dilute_its_strength() -> None:
    # The front sensors hear the tone in 60 % of the windows; in the others the
    # matcher lands on road noise at the floor. How often it is there is the
    # match rate's business; its strength is its level when it is there.
    def present(step: int) -> bool:
        return step % 5 < 3

    def absent(step: int) -> bool:
        return not present(step)

    fronts = ("front_left_wheel", "front_right_wheel")
    patchy = {
        location: [(_E2_PER_T1, 0.03, present), (_E2_PER_T1, _NOISE_G, absent)]
        for location in fronts
    }
    steady = {location: [(_E2_PER_T1, 0.03, _always)] for location in fronts}

    assert _engine_strength_db(patchy) == pytest.approx(_engine_strength_db(steady), abs=0.3)


def test_floor_level_matches_do_not_establish_an_orders_zone() -> None:
    # The front sensors hear the tone in 30 % of the windows and match road
    # noise at the floor in the rest. The matcher finds a peak every window,
    # but the order is there under half the time: not an established zone.
    def present(step: int) -> bool:
        return step % 10 < 3

    def absent(step: int) -> bool:
        return not present(step)

    summary = _analyse(
        {
            location: [(_E2_PER_T1, 0.05, present), (_E2_PER_T1, _NOISE_G, absent)]
            for location in ("front_left_wheel", "front_right_wheel")
        }
    )

    assert summary["diagnosis"]["confidence_level"] == "moderate"


def _heard_by_location(summary: dict, key: str) -> dict[str, set[bool]]:
    finding = next(f for f in summary["findings"] if f.get("finding_key") == key)
    heard: dict[str, set[bool]] = {}
    for point in finding["matched_points"]:
        heard.setdefault(point["location"], set()).add(point["heard"])
    return heard


def test_each_match_is_classified_once_as_heard_or_not() -> None:
    # The front sensors hear E2 clearly in every window. In the trunk the matcher
    # lands on floor-level noise, and every seventh window on a bump clear of the
    # floor: clear there far less often than at the front, so the trunk does not
    # hear the order and none of its matches is heard.
    def bump(step: int) -> bool:
        return step % 7 == 0

    summary = _analyse(
        {
            "front_left_wheel": [(_E2_PER_T1, 0.05, _always)],
            "front_right_wheel": [(_E2_PER_T1, 0.05, _always)],
            "trunk": [
                (_E2_PER_T1, _NOISE_G, lambda step: not bump(step)),
                (_E2_PER_T1, 0.012, bump),
            ],
        }
    )

    assert _heard_by_location(summary, "engine_2x") == {
        "Front Left Wheel": {True},
        "Front Right Wheel": {True},
        "Trunk": {False},
    }


def test_presence_counts_only_heard_matches() -> None:
    # The front sensors hear the tone in the first half of the drive; after that
    # the matcher lands on floor-level noise on its frequency.
    def first_half(step: int) -> bool:
        return step < 30

    summary = _analyse(
        {
            location: [
                (_E2_PER_T1, 0.05, first_half),
                (_E2_PER_T1, _NOISE_G, lambda step: not first_half(step)),
            ]
            for location in ("front_left_wheel", "front_right_wheel")
        }
    )

    assert summary["diagnosis"]["presence_ratio"] == pytest.approx(0.5, abs=0.05)


def test_the_speed_range_is_where_the_order_is_heard() -> None:
    # The front sensors hear the tone only around 80-90 km/h of a 50-115 km/h
    # sweep; elsewhere the matcher lands on floor-level noise on its frequency.
    def heard_band(step: int) -> bool:
        return 80.0 <= 50.0 + 65.0 * step / 59 <= 90.0

    summary = _analyse(
        {
            location: [
                (_E2_PER_T1, 0.05, heard_band),
                (_E2_PER_T1, _NOISE_G, lambda step: not heard_band(step)),
            ]
            for location in ("front_left_wheel", "front_right_wheel")
        }
    )

    diagnosis = summary["diagnosis"]
    assert diagnosis["source"] == "engine"
    assert 79.0 <= diagnosis["speed_min_kmh"] <= diagnosis["speed_max_kmh"] <= 91.0
    assert "narrow_speed_range" in diagnosis["weak_reasons"]


def test_a_fixed_tone_is_not_tracked_by_the_floor_noise_around_it() -> None:
    # A resonance at one frequency, clear of the floor at every sensor, which the
    # E2 path crosses around 82 km/h. In the rest of the sweep the matcher lands
    # on floor-level noise exactly on E2's predicted frequency: that follows the
    # prediction, but it is not the order. The heard matches stay at one
    # frequency while the prediction moves, so E2 is not an order finding.
    resonance_hz = _E2_PER_T1 * wheel_hz(82.0)

    def crossing(step: int) -> bool:
        predicted = _E2_PER_T1 * wheel_hz(50.0 + 65.0 * step / 59)
        return abs(predicted - resonance_hz) <= 0.08 * predicted

    noise = [(_E2_PER_T1, _NOISE_G, lambda step: not crossing(step))]
    sensors = ("front_left_wheel", "front_right_wheel", *_REAR, "trunk")
    samples = _drive(dict.fromkeys(sensors, noise))
    for sample in samples:
        sample["top_peaks"].append({"hz": resonance_hz, "amp": 0.05})

    summary = run_analysis(samples, _metadata())

    assert not any(f.get("finding_key") == "engine_2x" for f in summary["findings"])


_LOCATIONS = ("Front Left Wheel", "Front Right Wheel", "Rear Left Wheel", "Rear Right Wheel")
_WINDOWS = 20


# A sensor hears the order when it is clear of the floor there at least half as
# often as at the sensor where it is clearest.
@pytest.mark.parametrize(
    ("clear", "heard_at"),
    [
        pytest.param([20, 10, 9, 0], _LOCATIONS[:2], id="half-as-often-is-heard"),
        pytest.param([12, 6, 5, 0], _LOCATIONS[:2], id="relative-to-the-clearest"),
        pytest.param([0, 0, 0, 0], (), id="clear-nowhere"),
    ],
)
def test_a_sensor_hears_an_order_when_clear_half_as_often_as_the_best(
    clear: list[int], heard_at: tuple[str, ...]
) -> None:
    sensors = _sensors_that_hear(
        dict.fromkeys(_LOCATIONS, _WINDOWS), dict(zip(_LOCATIONS, clear, strict=True))
    )

    assert sensors == frozenset(heard_at)


def _accumulator(
    heard: dict[str, int],
    matched: dict[str, int] | None = None,
    *,
    heard_locations: frozenset[str] | None = None,
) -> OrderMatchAccumulator:
    """A wheel order matched at four sensors, loud at front-left, quiet elsewhere.

    *heard* is how many of each sensor's matches the evidence stage heard.
    """
    matched = matched or dict.fromkeys(_LOCATIONS, _WINDOWS)
    points = [
        OrderMatchObservation(
            predicted_hz=10.0 + 0.5 * window,
            matched_hz=10.0 + 0.5 * window,
            rel_error=0.0,
            amp=0.03 if location == _LOCATIONS[0] else _NOISE_G,
            location=location,
            t_s=float(window),
            speed_kmh=50.0 + 3.0 * window,
            heard=window < heard.get(location, 0),
        )
        for location in _LOCATIONS
        for window in range(matched[location])
    ]
    return OrderMatchAccumulator(
        possible=_WINDOWS * len(_LOCATIONS),
        matched_points=points,
        matched_floor=[_FLOOR_G] * len(points),
        ref_sources={"speed+tire"},
        possible_by_speed_bin={},
        matched_by_speed_bin={},
        possible_by_phase={},
        matched_by_phase={},
        possible_by_location=dict.fromkeys(_LOCATIONS, _WINDOWS),
        matched_by_location=matched,
        has_phases=False,
        compliance=1.0,
        heard_locations=(
            frozenset(location for location, count in heard.items() if count)
            if heard_locations is None
            else heard_locations
        ),
    )


def test_an_order_heard_nowhere_is_judged_on_all_its_matches() -> None:
    # Nothing stands out of the floor: its floor-level matches are all there is.
    match = _accumulator({})

    assert [point for point, _floor in match.evidence] == match.matched_points


def test_the_match_rate_is_taken_where_the_order_is_heard() -> None:
    # Heard at the front (matched 18 and 16 of 20 windows); the rear sensors
    # matched floor noise in 4 windows each.
    matched = dict(zip(_LOCATIONS, (18, 16, 4, 4), strict=True))
    match = _accumulator(dict(zip(_LOCATIONS, (18, 8, 0, 0), strict=True)), matched)

    assert match.match_rate == pytest.approx(42 / 80)
    assert match.heard_match_rate == pytest.approx(34 / 40)
    assert match.heard_share == pytest.approx(26 / 34)


def _wheel_score(match: OrderMatchAccumulator, *, match_rate: float = 1.0) -> OrderFindingScore:
    context = OrderFindingBuildContext(
        effective_match_rate=match_rate,
        focused_speed_band=None,
        per_location_dominant=False,
        match_rate=match_rate,
        min_match_rate=0.25,
        constancy=0.0,
        steadiness=0.0,
        connected_locations=set(_LOCATIONS),
        lang="en",
    )
    wheel_1x = next(h for h in _order_hypotheses() if h.key == "wheel_1x")
    return score_order_finding(wheel_1x, match, context=context)


def test_only_sensors_that_hear_an_order_corroborate_it() -> None:
    # The same matches, scored once with the quiet sensors among those that hear
    # the order and once without: the sensors that only matched floor noise add
    # no corroboration.
    def confidence(heard_locations: tuple[str, ...]) -> float:
        match = _accumulator({_LOCATIONS[0]: _WINDOWS}, heard_locations=frozenset(heard_locations))
        return _wheel_score(match).confidence

    assert confidence(_LOCATIONS[:1]) < confidence(_LOCATIONS)


def _heard_half_the_drive(*, floor_matches: bool) -> OrderMatchAccumulator:
    """A wheel order front-left hears in the first half of the drive.

    With *floor_matches*, the matcher lands on road noise at the floor in the
    second half, a little off the predicted frequency, where the road is a
    little quieter.
    """
    points = []
    for window in range(_WINDOWS):
        heard = window < _WINDOWS // 2
        if not heard and not floor_matches:
            continue
        predicted_hz = 10.0 + 0.5 * window
        rel_error = 0.0 if heard else 0.05
        points.append(
            OrderMatchObservation(
                predicted_hz=predicted_hz,
                matched_hz=predicted_hz * (1.0 + rel_error),
                rel_error=rel_error,
                amp=0.03 if heard else _NOISE_G,
                location=_LOCATIONS[0],
                t_s=float(window),
                speed_kmh=50.0 + 3.0 * window,
                heard=heard,
            )
        )
    return OrderMatchAccumulator(
        possible=_WINDOWS * len(_LOCATIONS),
        matched_points=points,
        matched_floor=[_FLOOR_G if point.heard else 0.003 for point in points],
        ref_sources={"speed+tire"},
        possible_by_speed_bin={},
        matched_by_speed_bin={},
        possible_by_phase={},
        matched_by_phase={},
        possible_by_location=dict.fromkeys(_LOCATIONS, _WINDOWS),
        matched_by_location={_LOCATIONS[0]: len(points)},
        has_phases=False,
        compliance=1.0,
        heard_locations=frozenset({_LOCATIONS[0]}),
    )


def test_floor_level_matches_add_nothing_to_an_orders_score() -> None:
    # Level, frequency error and tracking, and the sample count come from the
    # heard matches; how often it is there is the match rate's business, which
    # the context fixes here.
    def score(*, floor_matches: bool) -> tuple[float, ...]:
        result = _wheel_score(_heard_half_the_drive(floor_matches=floor_matches), match_rate=0.5)
        return (
            result.confidence,
            result.absolute_strength_db,
            result.mean_relative_error,
            result.frequency_correlation,
            result.ranking_score,
        )

    assert score(floor_matches=True) == pytest.approx(score(floor_matches=False))


def test_windows_whose_order_lies_below_the_analysis_floor_do_not_dilute_it() -> None:
    # Spectra below 5 Hz are not analysed, so a wheel order at town speeds (under
    # about 35 km/h) cannot be heard there. A drive that is half town, half
    # 50-115 km/h with a clear wheel order whenever it can show is matched in
    # every window that could show it, not in half of them.
    town = [
        {**sample, "t_s": sample["t_s"] + 100.0, "speed_kmh": 20.0 + sample["speed_kmh"] / 10.0}
        for sample in _drive({})
    ]
    assert wheel_hz(31.5) < 5.0
    drive = _drive({"front_left_wheel": [(1.0, 0.05, _always)]}) + town
    summary = run_analysis(drive, _metadata())
    wheel = max(
        (f for f in summary["findings"] if f["suspected_source"] == "wheel/tire"),
        key=lambda f: f["confidence"],
    )
    assert wheel["evidence_metrics"]["match_rate"] == pytest.approx(1.0)


def _rotating(multiples: tuple[float, ...], amp_g: float) -> list:
    """One peak per window at E2 times each of *multiples* in turn."""
    return [
        (_E2_PER_T1 * multiple, amp_g, lambda step, k=k: step % len(multiples) == k)
        for k, multiple in enumerate(multiples)
    ]


@pytest.mark.parametrize(
    ("multiples", "expected"),
    [
        # A road-excited body mode under E2: a clear peak in every window,
        # scattered over the tolerance window. Not the order.
        ((0.94, 1.03, 0.97, 1.06), ("no_fault", None, None)),
        # The engine's E2 read through a speed that is off by up to 1 %: a line.
        ((0.99, 1.005, 1.0, 0.995), ("fault", "E2", "strong")),
    ],
)
def test_only_peaks_on_one_line_are_an_order(
    multiples: tuple[float, ...], expected: tuple[str, str | None, str | None]
) -> None:
    fronts = {
        location: _rotating(multiples, 0.05)
        for location in ("front_left_wheel", "front_right_wheel")
    }

    diagnosis = _analyse(fronts)["diagnosis"]

    assert (
        diagnosis["verdict"],
        diagnosis["order_code"],
        diagnosis["confidence_level"],
    ) == expected
