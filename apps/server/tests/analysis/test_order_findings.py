"""Which tracked orders become findings: match-rate rescue, evidence gate, aliases, shaft order.

Pure order-tracking rules whose effects the simulator benchmark cannot isolate.
"""

from __future__ import annotations

import pytest
from test_support.analysis import run_analysis
from test_support.core import standard_metadata, wheel_hz
from test_support.findings import make_finding
from test_support.synthetic_samples import make_sample

from vibesensor.analysis._reference_resolution import ESTIMATED_RPM_SOURCE
from vibesensor.analysis._run_input import normalize_run_metadata
from vibesensor.analysis.orders.heuristics import suppress_engine_aliases
from vibesensor.analysis.orders.match_rate import _compute_effective_match_rate
from vibesensor.analysis.orders.matching import OrderMatchAccumulator
from vibesensor.analysis.orders.physics import _driveshaft_hz
from vibesensor.domain.order_match import OrderMatchObservation
from vibesensor.recording.run_metadata import run_metadata_from_mapping
from vibesensor.recording.sensor_frame_mapping import sensor_frames_from_mappings


def _bins(*specs: tuple[str, int, int]) -> tuple[dict[str, int], dict[str, int]]:
    """Build possible/matched dicts from (label, possible, matched) tuples."""
    possible = {label: p for label, p, _m in specs}
    matched = {label: m for label, _p, m in specs}
    return possible, matched


def _run_rescue(
    match_rate: float,
    speed_specs: tuple[tuple[str, int, int], ...],
    *,
    min_match_rate: float = 0.25,
    possible_by_location: dict[str, int] | None = None,
    matched_by_location: dict[str, int] | None = None,
) -> tuple[float, str | None, bool]:
    """Call ``_compute_effective_match_rate`` with common defaults."""
    possible, matched = _bins(*speed_specs)
    return _compute_effective_match_rate(
        match_rate=match_rate,
        min_match_rate=min_match_rate,
        possible_by_speed_bin=possible,
        matched_by_speed_bin=matched,
        possible_by_location=possible_by_location or {},
        matched_by_location=matched_by_location or {},
    )


# Only the highest speed bin is a rescue candidate; it needs enough samples and a
# match rate above ``min_match_rate``. Per-location dominance is the last fallback.
@pytest.mark.parametrize(
    ("match_rate", "speed_specs", "location_counts", "expected"),
    [
        pytest.param(
            0.20,
            (("30-40 km/h", 10, 2), ("90-100 km/h", 10, 8)),
            None,
            (0.8, "90-100 km/h", False),
            id="highest-bin-qualifies",
        ),
        pytest.param(
            0.20,
            (("30-40 km/h", 10, 9), ("50-60 km/h", 6, 1), ("90-100 km/h", 8, 1)),
            None,
            (0.20, None, False),
            id="strong-low-speed-bin-not-rescued",
        ),
        pytest.param(
            0.20,
            (("40-50 km/h", 10, 3), ("70-80 km/h", 10, 8), ("90-100 km/h", 6, 1)),
            None,
            (0.20, None, False),
            id="strong-second-highest-bin-ignored",
        ),
        pytest.param(
            0.20,
            (("60-70 km/h", 10, 7), ("80-90 km/h", 10, 9), ("90-100 km/h", 10, 8)),
            None,
            (0.8, "90-100 km/h", False),
            id="highest-bin-wins-over-better-lower-bin",
        ),
        pytest.param(
            0.20,
            (
                ("30-40 km/h", 10, 10),
                ("60-70 km/h", 6, 1),
                ("70-80 km/h", 6, 1),
                ("90-100 km/h", 6, 1),
            ),
            None,
            (0.20, None, False),
            id="only-highest-bin-evaluated",
        ),
        pytest.param(
            0.50,
            (("80-90 km/h", 10, 8),),
            None,
            (0.50, None, False),
            id="no-rescue-when-global-rate-sufficient",
        ),
        pytest.param(0.10, (), None, (0.10, None, False), id="empty-speed-bins"),
        pytest.param(
            0.10,
            (("90-100 km/h", 2, 2),),
            None,
            (0.10, None, False),
            id="bin-with-too-few-samples-skipped",
        ),
        pytest.param(
            0.10,
            (("90-100 km/h", 6, 1),),
            ({"Front Left": 10}, {"Front Left": 8}),
            (0.8, None, True),
            id="per-location-fallback-after-speed-rescue-fails",
        ),
    ],
)
def test_compute_effective_match_rate(
    match_rate: float,
    speed_specs: tuple[tuple[str, int, int], ...],
    location_counts: tuple[dict[str, int], dict[str, int]] | None,
    expected: tuple[float, str | None, bool],
) -> None:
    possible_by_location, matched_by_location = location_counts or ({}, {})
    assert (
        _run_rescue(
            match_rate,
            speed_specs,
            possible_by_location=possible_by_location,
            matched_by_location=matched_by_location,
        )
        == expected
    )


def _make_accumulator(
    *,
    possible: int,
    matched: int,
    sample_indices: tuple[int, ...],
    matched_speed_bins: dict[str, int] | None = None,
    predicted_vals: list[float] | None = None,
    measured_vals: list[float] | None = None,
) -> OrderMatchAccumulator:
    if predicted_vals is None:
        predicted_vals = [50.0 + float(i) for i in range(matched)]
    if measured_vals is None:
        measured_vals = [value + 0.1 for value in predicted_vals]

    matched_points = [
        OrderMatchObservation(
            predicted_hz=predicted_vals[idx],
            matched_hz=measured_vals[idx],
            rel_error=abs(measured_vals[idx] - predicted_vals[idx]) / predicted_vals[idx],
            amp=0.05,
            location="front_left",
            speed_kmh=60.0 + float(idx),
            t_s=0.25 * float(sample_indices[idx]),
        )
        for idx in range(matched)
    ]
    speed_bins = matched_speed_bins or {"60-70": matched}
    return OrderMatchAccumulator(
        possible=possible,
        matched=matched,
        matched_amp=[0.05] * matched,
        matched_floor=[0.005] * matched,
        rel_errors=[0.01] * matched,
        predicted_vals=predicted_vals,
        measured_vals=measured_vals,
        matched_points=matched_points,
        ref_sources={"speed+tire"},
        possible_by_speed_bin={"60-70": possible},
        matched_by_speed_bin=speed_bins,
        possible_by_phase={},
        matched_by_phase={},
        possible_by_location={"front_left": possible},
        matched_by_location={"front_left": matched},
        has_phases=False,
        compliance=1.0,
        matched_sample_indices=sample_indices,
    )


def test_variable_speed_order_in_one_speed_bin_needs_broad_frequency_tracking() -> None:
    match = _make_accumulator(
        possible=20,
        matched=8,
        sample_indices=(4, 5, 6, 7, 8, 9, 10, 11),
        matched_speed_bins={"60-70": 8},
        predicted_vals=[50.0] * 8,
        measured_vals=[50.1] * 8,
    )

    assert match.is_eligible(feature_interval_s=0.25, steady_speed=False) is False


def test_weaker_engine_alias_of_a_wheel_order_is_suppressed() -> None:
    findings = [
        (
            0.5,
            make_finding(suspected_source=" Wheel/Tire ", confidence=0.60, ranking_score=0.5),
        ),
        (0.4, make_finding(suspected_source=" ENGINE ", confidence=0.50, ranking_score=0.4)),
    ]

    result = suppress_engine_aliases(findings)

    engine = [f for f in result if str(f.suspected_source).strip().lower() == "engine"]
    assert len(engine) == 1
    assert engine[0].effective_confidence == pytest.approx(0.30)


# A front-left wheel imbalance (T1 well above T2) with one wheel sensor and two
# cabin sensors that feel half of it, swept 50-115 km/h in top gear (ratio 0.8).
_CABIN_SHARE = {"front_left_wheel": 1.0, "driver_seat": 0.55, "trunk": 0.5}
_TOP_GEAR = 0.8


def _drive(
    *,
    e1_per_t1: float,
    wheel_fault: bool = True,
    engine_tone_g: float = 0.0,
    measured_rpm: bool = False,
) -> list[dict]:
    samples = []
    for step in range(60):
        speed_kmh = 50.0 + 65.0 * step / 59
        t1_hz = wheel_hz(speed_kmh)
        for index, (location, share) in enumerate(_CABIN_SHARE.items()):
            scale = share * (1.0 + 0.03 * ((step * 7 + index) % 5))
            peaks = [{"hz": 142.5, "amp": 0.004}]
            if wheel_fault:
                peaks += [
                    {"hz": t1_hz, "amp": 0.12 * scale},
                    {"hz": 2.0 * t1_hz, "amp": 0.04 * scale},
                ]
            if engine_tone_g:
                jitter = 1.0 + 0.03 * ((step * 3 + index) % 4)
                peaks.append({"hz": e1_per_t1 * t1_hz, "amp": engine_tone_g * jitter})
            sample = make_sample(
                t_s=step * 0.5,
                speed_kmh=speed_kmh,
                client_name=location,
                location=location,
                top_peaks=peaks,
                vibration_strength_db=28.0 * share,
                strength_floor_amp_g=0.004,
                engine_rpm=e1_per_t1 * t1_hz * 60.0,
            )
            # Recording stores RPM from OBD, or else the estimate from speed and gear.
            sample["engine_rpm_source"] = "obd2" if measured_rpm else ESTIMATED_RPM_SOURCE
            samples.append(sample)
    return samples


def _analyse(samples: list[dict], *, e1_per_t1: float) -> dict:
    metadata = standard_metadata(
        run_id="run-1", final_drive_ratio=e1_per_t1 / _TOP_GEAR, current_gear_ratio=_TOP_GEAR
    )
    return run_analysis(samples, metadata)


# The car's top gear puts the engine's first order on the wheel's second. The
# wheel orders lose confidence for spreading into the cabin; the engine order on
# T2 does not (an engine is diagnosed as a zone), although T1 is ~10 dB louder.
@pytest.mark.parametrize(
    ("measured_rpm", "source", "order_code"),
    [
        # RPM inferred from speed and gear is locked to T2: T1 shows it is the wheel.
        (False, "wheel/tire", "T1"),
        # Measured RPM gives the engine order a frequency of its own, so an engine
        # fault on T2's frequency is not explained away by a louder wheel order.
        (True, "engine", "E1"),
    ],
    ids=["estimated-rpm", "measured-rpm"],
)
def test_engine_order_on_a_wheel_harmonic_is_the_wheel_only_with_estimated_rpm(
    measured_rpm: bool, source: str, order_code: str
) -> None:
    samples = _drive(e1_per_t1=2.0, measured_rpm=measured_rpm)

    diagnosis = _analyse(samples, e1_per_t1=2.0)["diagnosis"]

    assert (diagnosis["source"], diagnosis["order_code"]) == (source, order_code)
    assert diagnosis["conditions"]["rpm_source"] == (
        "measured" if measured_rpm else "estimated_top_gear"
    )


def test_engine_tone_off_the_wheel_orders_keeps_its_score_next_to_a_louder_wheel() -> None:
    # E1 at 2.72 x T1 (between T2 and T3), 12 dB below the wheel's T1.
    def engine_confidence(*, wheel_fault: bool) -> float:
        samples = _drive(e1_per_t1=2.72, wheel_fault=wheel_fault, engine_tone_g=0.03)
        findings = _analyse(samples, e1_per_t1=2.72)["findings"]
        return next(f["confidence"] for f in findings if f["suspected_source"] == "engine")

    assert engine_confidence(wheel_fault=True) == pytest.approx(
        engine_confidence(wheel_fault=False)
    )


def _context(overrides: dict | None = None):
    return normalize_run_metadata(run_metadata_from_mapping(overrides or {}), file_name="test")


def _sample(**fields: object):
    return sensor_frames_from_mappings([fields])[0]


@pytest.mark.parametrize(
    ("sample", "overrides", "tire_m"),
    [
        ({"speed_kmh": 80.0}, {"final_drive_ratio": 3.5}, None),
        ({"speed_kmh": 80.0, "final_drive_ratio": 0.0}, {}, 2.0),
        ({"speed_kmh": 80.0, "final_drive_ratio": -1.0}, {}, 2.0),
    ],
    ids=["no-tire-circ", "zero-final-drive", "negative-final-drive"],
)
def test_driveshaft_order_needs_tire_and_final_drive(
    sample: dict, overrides: dict, tire_m: float | None
) -> None:
    assert (
        _driveshaft_hz(_sample(**sample), _context(overrides), tire_circumference_m=tire_m) is None
    )


def test_driveshaft_order_is_wheel_rate_times_final_drive() -> None:
    # 72 km/h = 20 m/s on a 2.0 m tire: 10 wheel turns/s, 35 shaft turns/s at 3.5:1.
    result = _driveshaft_hz(
        _sample(speed_kmh=72.0, final_drive_ratio=3.5), _context(), tire_circumference_m=2.0
    )
    assert result == pytest.approx(35.0)
