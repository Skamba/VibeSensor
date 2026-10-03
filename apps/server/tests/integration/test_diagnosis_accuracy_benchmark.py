"""Diagnosis accuracy benchmark: simulated drives through the real pipeline.

Each case replays a simulator scenario (the committed scripted scenarios plus a
few benchmark drives defined here) for two cars: the default car, whose engine
orders sit on top of wheel orders, and a car whose orders do not coincide.
Sensor waveforms come from the simulator's sensor model and go through UDP
ingest, clock sync, DSP, recording with raw capture, post-analysis, the
diagnosis and the report view (``test_support.sim_pipeline``).

Expectations are declared from what each scenario injects (which profile on
which sensors), never from the analysis code: order frequencies and markers are
checked against this module's own tire/ratio math.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
from pypdf import PdfReader
from test_support.sim_pipeline import BenchCar, BenchSensor, SimPipelineResult, run_sim_pipeline

from vibesensor.domain.locations import location_code_for_label
from vibesensor.recording.run_schema import GuidedPhaseName
from vibesensor.report.pdf import render_report_pdf
from vibesensor.report.view_model import build_report_view
from vibesensor.simulator.profiles import DEFAULT_SPEED_KMH, PROFILE_LIBRARY, Profile
from vibesensor.simulator.scripted_scenario_catalog import SCRIPTED_SCENARIOS
from vibesensor.simulator.scripted_scenario_models import PhaseOverride, ScenarioPhase
from vibesensor.simulator.scripted_targeting import apply_phase
from vibesensor.simulator.sim_client import SimClient, make_client_id

DEFAULT_CAR = BenchCar("Default car", 285.0, 30.0, 21.0, 3.08, 0.64)
# 3.4 x 0.8: engine orders fall between the wheel orders instead of on T2.
OTHER_CAR = BenchCar("Hatchback", 205.0, 55.0, 16.0, 3.4, 0.8)
CARS = {"default": DEFAULT_CAR, "other": OTHER_CAR}

# Distinct advertised names, MAC client ids and location codes, registered in
# an order unrelated to the location order so id/name/location joins matter.
SENSORS = (
    BenchSensor("VS-41 rear right", "rear_right_wheel"),
    BenchSensor("VS-07 trunk", "trunk"),
    BenchSensor("VS-12 front left", "front_left_wheel"),
    BenchSensor("VS-33 rear left", "rear_left_wheel"),
    BenchSensor("VS-25 front right", "front_right_wheel"),
)

WHEEL_ZONES = frozenset(
    {"front_left_wheel", "front_right_wheel", "rear_left_wheel", "rear_right_wheel"}
)
# A driveshaft tone strongest at the rear wheels points at the rear axle, or at
# the tunnel when the rear corners do not stand out together.
DRIVELINE_ZONES = {"rear_axle", "driveshaft_tunnel"}
# Levels from the evidence the scenario injects: one clearly dominant source over
# a real speed range is Strong; a fault spread over several corners, alternating
# between sides or present in under half the drive is Moderate (check first).
STRONG = frozenset({"strong"})
MODERATE = frozenset({"moderate"})
WEAK_ONLY = frozenset({"weak"})

_ZONE_TEXT_EN = {
    "front_left_wheel": "front-left wheel",
    "front_right_wheel": "front-right wheel",
    "rear_left_wheel": "rear-left wheel",
    "rear_right_wheel": "rear-right wheel",
    "rear_axle": "rear axle",
    "front_axle": "front axle",
    "all_wheels": "all four wheels",
    "engine_bay": "engine bay",
}


@dataclass(frozen=True, slots=True)
class Expected:
    """Ground truth for one scenario, from what the scenario injects."""

    verdicts: frozenset[str]
    source: str | None = None
    zones: frozenset[str] = frozenset()
    order_codes: frozenset[str] = frozenset()
    levels: frozenset[str] = STRONG
    speed_dependence: str | None = None
    # One corner carries the fault well above the others (single-wheel faults).
    dominant_corner: bool = False


@dataclass(frozen=True, slots=True)
class Case:
    case_id: str
    phases: tuple[ScenarioPhase, ...]
    expected: Expected
    by_car: dict[str, Expected] = field(default_factory=dict)
    # Share of DATA frames each location's sensor loses on the way to the server.
    frame_loss: dict[str, float] = field(default_factory=dict)
    # Extra delay (s) of 30 % of every sensor's clock-sync replies: busy Wi-Fi.
    uplink_latency_spike_s: float = 0.0

    def sensors(self) -> tuple[BenchSensor, ...]:
        return tuple(
            replace(
                sensor,
                frame_loss=self.frame_loss.get(sensor.location_code, 0.0),
                uplink_latency_spike_s=self.uplink_latency_spike_s,
            )
            for sensor in SENSORS
        )

    def expected_for(self, car: str) -> Expected:
        return self.by_car.get(car, self.expected)


def _fault(source: str, zones: set[str], order: str, **kwargs: object) -> Expected:
    return Expected(
        verdicts=frozenset({"fault"}),
        source=source,
        zones=frozenset(zones),
        order_codes=frozenset({order}),
        **kwargs,  # type: ignore[arg-type]
    )


NO_FAULT = Expected(verdicts=frozenset({"no_fault"}), levels=frozenset())


def _scripted(name: str, expected: Expected, **by_car: Expected) -> Case:
    return Case(name, SCRIPTED_SCENARIOS[name].phases, expected, dict(by_car))


# -- benchmark drives (not in the simulator catalog) ---------------------------


def _ov(target: str, profile: str, gain: float, amp: float) -> PhaseOverride:
    return PhaseOverride(
        target=target,
        profile_name=profile,
        scene_gain=gain,
        scene_noise_gain=1.0,
        amp_scale=amp,
        noise_scale=1.0,
    )


_ROAD = _ov("all", "rough_road", 0.28, 0.52)


def _phase(
    name: str,
    duration_s: float,
    start: float,
    end: float,
    *ovs: PhaseOverride,
    guided: GuidedPhaseName | None = None,
) -> ScenarioPhase:
    return ScenarioPhase(
        name=name,
        duration_s=duration_s,
        speed_start_kmh=start,
        speed_end_kmh=end,
        overrides=(_ROAD, *ovs),
        guided_phase=guided,
    )


# An engine whose first order dominates (crank pulley or flywheel imbalance). On
# the default car E1 sits on T2, so only the neutral coast-down can tell it from
# a wheel. Benchmark-only simulator profile, registered by ``_bench_profiles``.
_ENGINE_FIRST_ORDER = Profile(
    name="bench_engine_first_order",
    tones=(),
    order_tones=(("engine_1x", 1.0, (190.0, 130.0, 250.0)),),
    noise_std=18.0,
    bump_probability=0.001,
    bump_decay=0.96,
    bump_strength=(16.0, 13.0, 24.0),
    modulation_hz=0.24,
    modulation_depth=0.10,
    reference_speed_kmh=DEFAULT_SPEED_KMH,
)
# An out-of-round tire: twice per wheel turn dominates, well over 3 dB above T1.
_TIRE_OUT_OF_ROUND = Profile(
    name="bench_tire_out_of_round",
    tones=(),
    order_tones=(
        ("wheel_2x", 1.0, (210.0, 120.0, 165.0)),
        ("wheel_1x", 1.0, (60.0, 35.0, 48.0)),
    ),
    noise_std=24.0,
    bump_probability=0.004,
    bump_decay=0.94,
    bump_strength=(30.0, 24.0, 45.0),
    modulation_hz=0.22,
    modulation_depth=0.12,
    reference_speed_kmh=DEFAULT_SPEED_KMH,
)
_BENCH_PROFILES = {profile.name: profile for profile in (_ENGINE_FIRST_ORDER, _TIRE_OUT_OF_ROUND)}


@pytest.fixture(autouse=True)
def _bench_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, profile in _BENCH_PROFILES.items():
        monkeypatch.setitem(PROFILE_LIBRARY, name, profile)


def _sweep(*faults: PhaseOverride) -> tuple[ScenarioPhase, ...]:
    """Sweep 50->115 km/h, hold 90, then a short coast to 70."""
    return (
        _phase("sweep", 12.0, 50.0, 115.0, *faults),
        _phase("hold", 6.0, 90.0, 90.0, *faults),
        _phase("coast", 4.0, 90.0, 70.0, *faults),
    )


BENCH_CASES = (
    Case("bench-healthy-sweep", _sweep(), NO_FAULT),
    # Fixed-frequency body resonances (13/26/39 Hz) that the orders sweep through:
    # brief crossings are not an order-tracked fault.
    # At most a hedged guess, never an actionable fault.
    Case(
        "bench-fixed-resonance-sweep",
        _sweep(_ov("all", "engine_idle", 0.5, 0.8)),
        Expected(verdicts=frozenset({"no_fault", "weak_evidence"}), levels=WEAK_ONLY),
    ),
    Case(
        "bench-rear-right-wheel-sweep",
        _sweep(
            _ov("rear-right", "wheel_imbalance", 0.85, 1.0),
            _ov("rear-left", "wheel_mild_imbalance", 0.30, 0.55),
        ),
        _fault("wheel/tire", {"rear_right_wheel"}, "T1", dominant_corner=True),
    ),
    # A mild imbalance (about 20 mg at its corner, ten times the other sensors):
    # quiet elsewhere on the car, yet clearly the one source at that corner.
    Case(
        "bench-mild-front-left-wheel-sweep",
        _sweep(_ov("front-left", "wheel_mild_imbalance", 0.15, 1.0)),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True),
    ),
    # Barely above the road noise: found and located, but never "go fix it".
    Case(
        "bench-barely-there-front-left-wheel-sweep",
        _sweep(_ov("front-left", "wheel_mild_imbalance", 0.06, 1.0)),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", levels=frozenset({"moderate", "weak"})),
    ),
    Case(
        "bench-rear-left-out-of-round-sweep",
        _sweep(_ov("rear-left", _TIRE_OUT_OF_ROUND.name, 0.85, 1.0)),
        _fault("wheel/tire", {"rear_left_wheel"}, "T2", dominant_corner=True),
    ),
    # Same fault, but the faulty corner's sensor loses 15 % of its frames over
    # Wi-Fi: still diagnosed, and the report says data was lost.
    Case(
        "bench-rear-right-wheel-sweep-lossy-sensor",
        _sweep(
            _ov("rear-right", "wheel_imbalance", 0.85, 1.0),
            _ov("rear-left", "wheel_mild_imbalance", 0.30, 0.55),
        ),
        _fault("wheel/tire", {"rear_right_wheel"}, "T1", dominant_corner=True),
        frame_loss={"rear_right_wheel": 0.15},
    ),
    # Busy Wi-Fi: slow, one-sided clock-sync replies must not throw the sensor
    # clocks off, so the run stays (mostly) raw-backed.
    Case(
        "bench-rear-right-wheel-sweep-busy-wifi",
        _sweep(
            _ov("rear-right", "wheel_imbalance", 0.85, 1.0),
            _ov("rear-left", "wheel_mild_imbalance", 0.30, 0.55),
        ),
        _fault("wheel/tire", {"rear_right_wheel"}, "T1", dominant_corner=True),
        uplink_latency_spike_s=0.03,
    ),
    Case(
        "bench-driveline-sweep",
        _sweep(
            _ov("rear-axle", "driveshaft_imbalance", 0.80, 0.95),
            _ov("front-axle", "driveshaft_imbalance", 0.35, 0.60),
        ),
        _fault("driveline", DRIVELINE_ZONES, "P1"),
    ),
    Case(
        "bench-engine-sweep",
        _sweep(
            _ov("front-axle", "engine_order", 0.74, 0.94),
            _ov("rear-axle", "engine_order", 0.42, 0.94),
        ),
        _fault("engine", {"engine_bay"}, "E2"),
    ),
    # Guided test: the vibration stops when the engine drops to idle in neutral.
    # Whatever the frequency suggests, it must not be sent to the tire shop.
    Case(
        "bench-guided-engine-first-order",
        (
            _phase(
                "sweep",
                8.0,
                50.0,
                100.0,
                _ov("all", _ENGINE_FIRST_ORDER.name, 0.7, 0.9),
                guided="sweep",
            ),
            _phase(
                "hold",
                6.0,
                100.0,
                100.0,
                _ov("all", _ENGINE_FIRST_ORDER.name, 0.7, 0.9),
                guided="hold",
            ),
            _phase(
                "coast", 10.0, 100.0, 70.0, _ov("all", "engine_idle", 0.2, 0.6), guided="coast_down"
            ),
        ),
        _fault("engine", {"engine_bay"}, "E1", speed_dependence="engine_speed"),
        # On the default car E1 coincides with T2: right source, less certain.
        {
            "default": _fault(
                "engine", {"engine_bay"}, "E1", speed_dependence="engine_speed", levels=MODERATE
            )
        },
    ),
    Case(
        "bench-faint-intermittent-engine",
        (
            _phase("a", 6.0, 75.0, 75.0, _ov("front-axle", "engine_order", 0.30, 0.6)),
            _phase("b", 8.0, 75.0, 76.0),
            _phase("c", 6.0, 76.0, 76.0, _ov("front-axle", "engine_order", 0.30, 0.6)),
            _phase("d", 8.0, 76.0, 75.0),
        ),
        # Faint and present in under half the drive: never a Strong verdict.
        Expected(
            verdicts=frozenset({"weak_evidence", "no_fault", "fault"}),
            source="engine",
            zones=frozenset({"engine_bay"}),
            # At an almost steady speed the louder E2 tone can pass for a fixed
            # resonance, leaving E1 as the tracked engine order.
            order_codes=frozenset({"E1", "E2"}),
            levels=frozenset({"weak", "moderate"}),
        ),
        # On the default car E1 sits on T2, so a faint engine tone may only be
        # named as a hedged guess; the run must not read as an actionable fault.
        {"default": Expected(verdicts=frozenset({"weak_evidence", "no_fault"}), levels=WEAK_ONLY)},
    ),
)

SCRIPTED_CASES = (
    _scripted(
        "accel-front-left-surge",
        _fault("wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True),
    ),
    _scripted(
        "coastdown-rear-right-rumble",
        _fault("wheel/tire", {"rear_right_wheel"}, "T1", dominant_corner=True),
    ),
    # Every wheel carries the same mild imbalance inside the speed window.
    _scripted(
        "highway-window-shudder",
        _fault("wheel/tire", {"all_wheels"}, "T1", levels=MODERATE),
    ),
    _scripted("launch-engine-flare", _fault("engine", {"engine_bay"}, "E2")),
    _scripted("pothole-recovery-loop", NO_FAULT),
    # Left-side wheels, then right-side wheels: any one wheel, spread evidence.
    _scripted(
        "lane-change-left-right",
        _fault("wheel/tire", set(WHEEL_ZONES), "T1", levels=MODERATE),
    ),
    _scripted(
        "rear-left-cruise-rumble",
        _fault("wheel/tire", {"rear_left_wheel"}, "T1", dominant_corner=True),
    ),
    _scripted(
        "front-right-cruise-shimmy",
        _fault("wheel/tire", {"front_right_wheel"}, "T1", dominant_corner=True),
    ),
    # The driveshaft tone is strongest on the rear-axle sensors; present in
    # about 40 % of the drive, so the default car lands on Moderate.
    _scripted(
        "driveline-coastdown",
        _fault("driveline", DRIVELINE_ZONES, "P1", levels=MODERATE),
    ),
    # Front-left first, then rear-right: either corner is right.
    _scripted(
        "dual-fault-recovery",
        _fault("wheel/tire", {"front_left_wheel", "rear_right_wheel"}, "T1"),
    ),
    _scripted(
        "guided-wheel-coastdown",
        _fault(
            "wheel/tire",
            {"front_left_wheel"},
            "T1",
            speed_dependence="vehicle_speed",
            dominant_corner=True,
        ),
    ),
    _scripted(
        "guided-engine-coastdown",
        _fault("engine", {"engine_bay"}, "E2", speed_dependence="engine_speed"),
    ),
)

CASES = (*SCRIPTED_CASES, *BENCH_CASES)

# One drive per report variant (fault, weak evidence, no fault) is also rendered
# to PDF, in English and Dutch, and checked by its text.
PDF_CASES = frozenset(
    {
        ("front-right-cruise-shimmy", "default"),
        ("bench-faint-intermittent-engine", "default"),
        ("bench-healthy-sweep", "other"),
    }
)
_PDF_HEADLINES = {
    "fault": ("likely cause:", "waarschijnlijke oorzaak:"),
    "weak_evidence": (
        "not enough evidence to name a cause",
        "onvoldoende bewijs om een oorzaak te noemen",
    ),
    "no_fault": ("no significant vibration found", "geen noemenswaardige trilling gevonden"),
}

# The simulator's order tone (profile key, multiple) behind each order label.
_ORDER_TONES = {
    "T1": ("wheel_1x", 1.0),
    "T2": ("wheel_2x", 1.0),
    "P1": ("shaft_1x", 1.0),
    "P2": ("shaft_1x", 2.0),
    "E1": ("engine_1x", 1.0),
    "E2": ("engine_2x", 1.0),
}
_SIM_MG_PER_COUNT = 1000.0 / 256.0  # ADXL345 full-resolution counts


def injected_order_mg(phases: tuple[ScenarioPhase, ...], order_code: str) -> dict[str, float]:
    """Peak order-tone amplitude (mg, 3-axis vector) each location receives in any phase."""
    tone = _ORDER_TONES[order_code]
    clients = [
        SimClient(
            name=sensor.advertised_name,
            client_id=make_client_id(index + 1),
            control_port=0,
            sample_rate_hz=800,
            frame_samples=200,
            server_host="",
            server_data_port=0,
            server_control_port=0,
            profile_name="rough_road",
        )
        for index, sensor in enumerate(SENSORS)
    ]
    injected = {sensor.location_code: 0.0 for sensor in SENSORS}
    for phase in phases:
        apply_phase(clients, "ground-truth", phase)
        for sensor, client in zip(SENSORS, clients, strict=True):
            counts = sum(
                math.hypot(*amps)
                for key, multiple, amps in PROFILE_LIBRARY[client.profile_name].order_tones
                if (key, multiple) == tone
            )
            mg = counts * client.scene_gain * client.amp_scale * _SIM_MG_PER_COUNT
            injected[sensor.location_code] = max(injected[sensor.location_code], mg)
    return injected


_ORDER_MULTIPLE = {"T1": 1.0, "T2": 2.0, "P1": 1.0, "P2": 2.0, "E1": 1.0, "E2": 2.0}


def _order_hz(car: BenchCar, code: str, speed_kmh: float) -> float:
    orders = car.order_hz(speed_kmh)
    base = {"T": orders["wheel_1x"], "P": orders["shaft_1x"], "E": orders["engine_1x"]}[code[0]]
    return base * _ORDER_MULTIPLE[code]


# Known accuracy misses: the benchmark keeps them visible (strict xfail) until fixed.
KNOWN_MISSES = {
    ("guided-engine-coastdown", "default"): (
        "the idle tone at 39 Hz matches E2 (~0.51 Hz per km/h) while coasting through "
        "71-82 km/h, so the coast-down reads as following road speed and the engine "
        "fault is demoted to weak evidence"
    ),
}

# Misses that only some sensor-id seeds hit (opt-in matrix only).
MATRIX_KNOWN_MISSES = {
    ("bench-fixed-resonance-sweep", "default"): (
        "brief crossings of the fixed 13/26/39 Hz resonances read as a Moderate "
        "all-wheels T1/T2 fault in 2 of 6 seeds"
    ),
}

# Every case runs on one sensor-id seed in default CI; the opt-in matrix repeats
# each case over more seeds (different MACs, so different noise and clock drift).
CI_SEED = 1
MATRIX_SEEDS = (2, 3, 4, 5, 6)
MATRIX_MIN_PASSES = 4


def _case_params(*, matrix: bool = False) -> list[object]:
    params: list[object] = []
    for case in CASES:
        for car_key in sorted(CARS):
            miss = KNOWN_MISSES.get((case.case_id, car_key))
            if matrix and miss is None:
                miss = MATRIX_KNOWN_MISSES.get((case.case_id, car_key))
            marks = [pytest.mark.xfail(reason=miss, strict=True)] if miss else []
            params.append(pytest.param(case, car_key, id=f"{case.case_id}-{car_key}", marks=marks))
    return params


def _run_case(case: Case, car_key: str, seed: int, tmp_path: Path) -> None:
    car = CARS[car_key]
    result = run_sim_pipeline(
        tmp_path,
        car=car,
        sensors=case.sensors(),
        scenario_name=case.case_id,
        phases=case.phases,
        client_seed=seed,
    )
    try:
        lossy = bool(case.frame_loss)
        _assert_case(result, car, case.expected_for(car_key), case.phases, lossy=lossy)
        _assert_frame_integrity(result, lossy=lossy)
        if (case.case_id, car_key) in PDF_CASES:
            _assert_pdf_text(result)
    finally:
        result.history_db.close()


@pytest.mark.parametrize(("case", "car_key"), _case_params())
def test_diagnosis_accuracy(case: Case, car_key: str, tmp_path: Path) -> None:
    _run_case(case, car_key, CI_SEED, tmp_path)


@pytest.mark.diagnostic_matrix
@pytest.mark.parametrize(("case", "car_key"), _case_params(matrix=True))
def test_diagnosis_accuracy_across_seeds(case: Case, car_key: str, tmp_path: Path) -> None:
    failures: list[str] = []
    for seed in MATRIX_SEEDS:
        try:
            _run_case(case, car_key, seed, tmp_path / f"seed-{seed}")
        except AssertionError as exc:
            failures.append(f"seed {seed}: {str(exc).splitlines()[0]}")
    passes = len(MATRIX_SEEDS) - len(failures)
    assert passes >= MATRIX_MIN_PASSES, "\n".join(failures)


def _assert_case(
    result: SimPipelineResult,
    car: BenchCar,
    expected: Expected,
    phases: tuple[ScenarioPhase, ...],
    *,
    lossy: bool = False,
) -> None:
    diagnosis = result.diagnosis
    summary = (
        f"verdict={diagnosis['verdict']} level={diagnosis['confidence_level']} "
        f"source={diagnosis['source']} zone={diagnosis['zone']} "
        f"order={diagnosis['order_code']} location={diagnosis['location']} "
        f"weak={diagnosis['weak_reasons']} speed_dep={diagnosis['speed_dependence']}"
    )
    assert diagnosis["verdict"] in expected.verdicts, summary
    if diagnosis["verdict"] == "no_fault":
        assert diagnosis["source"] is None and diagnosis["zone"] is None, summary
        assert diagnosis["confidence_level"] is None, summary
    elif expected.source is None:
        # Hedged guess only: the cause is not part of the expectation.
        assert diagnosis["confidence_level"] in expected.levels, summary
    else:
        assert diagnosis["source"] == expected.source, summary
        assert diagnosis["zone"] in expected.zones, summary
        assert diagnosis["order_code"] in expected.order_codes, summary
        assert diagnosis["confidence_level"] in expected.levels, summary
        _assert_order_frequency(diagnosis, car, summary)
        _assert_order_amplitude_mg(diagnosis, phases)
    if expected.speed_dependence is not None:
        assert diagnosis["speed_dependence"] == expected.speed_dependence, summary
    _assert_spectrum_markers(diagnosis, car)
    _assert_sensor_identity(result)
    _assert_raw_backed(result, lossy=lossy)
    _assert_report_view(result, diagnosis, expected)


def _assert_order_amplitude_mg(diagnosis: dict, phases: tuple[ScenarioPhase, ...]) -> None:
    """The strongest location's mg level is on the scale of the tone the simulator injected.

    It is a median over the run's matched windows (single-axis band level, smeared
    while the speed ramps), so it reads a fraction of the injected 3-axis peak:
    about a quarter at steady speed, a few percent on fast sweeps; a unit error is
    off by 10x or more.
    """
    assert diagnosis["amplitude_basis"] == "order"
    strongest = diagnosis["location_amplitudes"][0]
    code = location_code_for_label(strongest["location"])
    injected = injected_order_mg(phases, diagnosis["order_code"])[code]
    assert injected > 0, (strongest, diagnosis["order_code"])
    assert injected / 40.0 <= strongest["amplitude_mg"] <= injected / 3.0, (strongest, injected)


def _assert_order_frequency(diagnosis: dict, car: BenchCar, summary: str) -> None:
    """The reported frequency follows the order at the reported speed (own tire/ratio math).

    Spectra average ~2.5 s, so on a speed ramp the measured Hz per km/h lags by a
    few percent; a wrong order or tire size is off by 10 % or more.
    """
    speed = diagnosis["reference_speed_kmh"]
    frequency = diagnosis["frequency_hz"]
    assert speed is not None and frequency is not None, summary
    expected_hz = _order_hz(car, diagnosis["order_code"], speed)
    assert frequency == pytest.approx(expected_hz, rel=0.06), summary


def _assert_spectrum_markers(diagnosis: dict, car: BenchCar) -> None:
    spectrum = diagnosis["spectrum"]
    if spectrum is None:
        return
    markers = spectrum["order_markers"]
    low = car.wheel_hz(spectrum["speed_min_kmh"])
    high = car.wheel_hz(spectrum["speed_max_kmh"])
    assert low * 0.98 <= markers["T1"] <= high * 1.02, markers
    assert markers["T2"] == pytest.approx(2.0 * markers["T1"], rel=1e-6)
    assert markers["P1"] == pytest.approx(car.final_drive_ratio * markers["T1"], rel=1e-6)
    assert markers["P2"] == pytest.approx(2.0 * markers["P1"], rel=1e-6)
    assert markers["E1"] == pytest.approx(car.current_gear_ratio * markers["P1"], rel=1e-6)
    assert markers["E2"] == pytest.approx(2.0 * markers["E1"], rel=1e-6)


def _assert_sensor_identity(result: SimPipelineResult) -> None:
    """Persisted rows join each MAC to the location it was given, never to its name."""
    by_client: dict[str, set[tuple[str, str]]] = {}
    for batch in result.history_db.iter_run_samples(result.run_id, batch_size=2048):
        for row in batch:
            by_client.setdefault(row.client_id, set()).add((row.client_name, row.location))
    expected = {client_id: code for code, client_id in result.client_ids.items()}
    assert set(by_client) == set(expected)
    for client_id, seen in by_client.items():
        assert {location for _name, location in seen} == {expected[client_id]}
        assert all(name and name != client_id for name, _location in seen)


def _assert_frame_integrity(result: SimPipelineResult, *, lossy: bool) -> None:
    checks = {check.label: check for check in result.report.quality.checks}
    frame_integrity = checks["Frame integrity"]
    assert frame_integrity.passed is not lossy, frame_integrity
    if lossy:
        assert "dropped frames" in frame_integrity.detail
        assert not result.report.quality.all_passed


def _assert_raw_backed(result: SimPipelineResult, *, lossy: bool) -> None:
    """Every sensor clock-synced before the drive, so analysis replays the raw capture.

    Only the first ~2.5 s of rows (whose FFT window reaches back before the
    recording started) have no raw samples to replay.
    """
    metadata = result.analysis.payload["analysis_metadata"]
    assert isinstance(metadata, dict)
    assert metadata["raw_capture_mode"] in {"raw_backed", "partial_raw_backed"}, metadata
    raw_backed, total = metadata["raw_backed_sample_count"], metadata["total_sample_count"]
    assert isinstance(raw_backed, int) and isinstance(total, int)
    if lossy:
        # The lossy sensor's frame gaps leave its rows to the stored summaries.
        assert raw_backed >= 0.6 * total, metadata
        return
    assert raw_backed >= 0.85 * total, metadata
    assert metadata["raw_replay_sample_rate_unverified_sensor_count"] == 0
    assert metadata["raw_replay_timing_fallback_count"] == 0


# What the owner is told to have checked, per diagnosed order.
_NEXT_STEP_KEYWORDS = {"T1": "balanced", "T2": "out-of-round", "P1": "propshaft", "E2": "mounts"}


def _assert_report_view(result: SimPipelineResult, diagnosis: dict, expected: Expected) -> None:
    # The mechanic's worksheet lists each order once; where it was strongest is
    # in the per-location table.
    worksheet_orders = [row.order for row in result.report.mechanic.worksheet]
    assert len(worksheet_orders) == len(set(worksheet_orders)), worksheet_orders
    owner = result.report.owner
    assert owner.verdict == diagnosis["verdict"]
    assert owner.level == diagnosis["confidence_level"]
    if diagnosis["verdict"] == "no_fault":
        assert owner.headline == "No significant vibration found"
        assert owner.diagram.zone is None
        return
    zone_text = _ZONE_TEXT_EN.get(diagnosis["zone"])
    if zone_text is not None:
        cause_text = owner.headline if diagnosis["verdict"] == "fault" else owner.candidate
        assert cause_text is not None and zone_text in cause_text, cause_text
    assert owner.diagram.zone == diagnosis["zone"]
    level_words = {"strong": "Strong", "moderate": "Moderate", "weak": "Weak"}
    assert owner.level_word == level_words[diagnosis["confidence_level"]]
    rows = [row for row in diagnosis["location_amplitudes"] if row["amplitude_mg"] is not None]
    strongest = [marker for marker in owner.diagram.markers if marker.strongest]
    assert len(strongest) == 1 and rows
    assert strongest[0].value.endswith(" mg")
    if diagnosis["verdict"] == "fault":
        assert owner.verify is not None
        assert f"{diagnosis['order_code']} " in owner.verify
        assert owner.verify.rstrip(".").endswith("mg today")
        keyword = _NEXT_STEP_KEYWORDS.get(diagnosis["order_code"])
        if keyword is not None:
            assert keyword in owner.next_step, owner.next_step
    if expected.dominant_corner and diagnosis["verdict"] == "fault":
        corner = _ZONE_TEXT_EN[diagnosis["zone"]]
        assert f"stronger at the {corner} than at the next sensor" in owner.description, (
            owner.description
        )


def _assert_pdf_text(result: SimPipelineResult) -> None:
    verdict = result.diagnosis["verdict"]
    for lang, headline in zip(("en", "nl"), _PDF_HEADLINES[verdict], strict=True):
        view = build_report_view(result.analysis.payload, result.metadata, lang=lang)
        reader = PdfReader(io.BytesIO(render_report_pdf(view)))
        pages = [" ".join((page.extract_text() or "").split()).lower() for page in reader.pages]
        assert len(pages) >= 2
        assert headline in pages[0], pages[0][:300]
        # Levels only, never a confidence percentage (page 1 is the owner page).
        assert "%" not in pages[0]
        if verdict == "fault":
            assert view.owner.next_step.lower()[:40] in pages[0]
            assert view.owner.verify is not None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "known miss: rows from the first ~2.5 s after the start have FFT windows that "
        "reach back before the raw capture began, so every recording reads as "
        "partially raw-backed and the report always warns that raw data was missing"
    ),
)
def test_clean_drive_report_passes_every_data_check(tmp_path: Path) -> None:
    case = next(case for case in CASES if case.case_id == "front-right-cruise-shimmy")
    result = run_sim_pipeline(
        tmp_path,
        car=DEFAULT_CAR,
        sensors=SENSORS,
        scenario_name=case.case_id,
        phases=case.phases,
        client_seed=CI_SEED,
    )
    try:
        quality = result.report.quality
        assert all(check.passed for check in quality.checks)
        assert quality.all_passed, quality.warnings
    finally:
        result.history_db.close()
