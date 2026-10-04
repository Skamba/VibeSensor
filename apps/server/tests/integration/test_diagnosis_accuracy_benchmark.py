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
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
from pypdf import PdfReader
from test_support.sim_pipeline import (
    BenchCar,
    BenchSensor,
    SimPipelineResult,
    SpeedSource,
    run_sim_pipeline,
)

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

# Other layouts owners use: one sensor, sensors in the cabin only, one wheel
# sensor plus the cabin, or a sensor on every mounting point.
ONE_SENSOR = (BenchSensor("VS-12 front left", "front_left_wheel"),)
CABIN_ONLY = (
    BenchSensor("VS-50 driver seat", "driver_seat"),
    BenchSensor("VS-07 trunk", "trunk"),
    BenchSensor("VS-61 passenger seat", "front_passenger_seat"),
)
ONE_WHEEL_AND_CABIN = (
    BenchSensor("VS-12 front left", "front_left_wheel"),
    BenchSensor("VS-50 driver seat", "driver_seat"),
    BenchSensor("VS-07 trunk", "trunk"),
)
EVERY_MOUNT = (
    *SENSORS,
    BenchSensor("VS-50 driver seat", "driver_seat"),
    BenchSensor("VS-61 passenger seat", "front_passenger_seat"),
    BenchSensor("VS-70 engine", "engine_bay"),
    BenchSensor("VS-71 tunnel", "driveshaft_tunnel"),
    BenchSensor("VS-72 gearbox", "transmission"),
    BenchSensor("VS-73 centre seat", "rear_center_seat"),
    BenchSensor("VS-74 subframe", "front_subframe"),
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
_CABIN_TEXT = {
    "driver_seat": ("driver seat", "bestuurdersstoel"),
    "trunk": ("boot", "kofferbak"),
    "front_passenger_seat": ("front passenger seat", "bijrijdersstoel"),
}
# A wheel fault felt only in the cabin: no wheel named, and the owner is told to
# put sensors at the wheels to find it.
_UNLOCATED_WHEEL_TEXT = {
    "en": (
        "could not be pinned to one wheel",
        "felt strongest at the {}",
        "a sensor at each wheel",
    ),
    "nl": (
        "niet aan één wiel te koppelen",
        "het sterkst gevoeld bij {}",
        "bij elk wiel een sensor",
    ),
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
    # What a weak-evidence report must say made the run hard to judge.
    weak_reasons: frozenset[str] = frozenset()


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
    # Recording starts right at car start, before the sensor clocks are synced.
    car_start: bool = False
    # Share of DATA transmissions every sensor has to retry (congested Wi-Fi).
    wifi_retry_loss: float = 0.0
    # Where the owner mounted the sensors.
    layout: tuple[BenchSensor, ...] = SENSORS
    # How the measured speed of the drive reaches the server.
    speed_source: SpeedSource = "gps"

    def sensors(self) -> tuple[BenchSensor, ...]:
        return tuple(
            replace(
                sensor,
                frame_loss=self.frame_loss.get(sensor.location_code, 0.0),
                uplink_latency_spike_s=self.uplink_latency_spike_s,
                wifi_retry_loss=self.wifi_retry_loss,
            )
            for sensor in self.layout
        )

    @property
    def clean_network(self) -> bool:
        """Every sensor synced before the start and no data was lost on the way."""
        return (
            not self.frame_loss
            and self.uplink_latency_spike_s == 0
            and self.wifi_retry_loss == 0
            and not self.car_start
        )

    def expected_for(self, car: str) -> Expected:
        return self.by_car.get(car, self.expected)

    @property
    def wheel_sensors(self) -> bool:
        return any(sensor.location_code in WHEEL_ZONES for sensor in self.layout)

    @property
    def stands_still(self) -> bool:
        return any(phase.speed_start_kmh == 0 == phase.speed_end_kmh for phase in self.phases)


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
# An unbalanced tire that is also oval: once and twice per turn about equally
# strong (T2 ~1 dB above T1). Balancing is the cheap first fix, so the diagnosis
# stays on the fundamental unless the 2nd order clearly dominates.
_IMBALANCED_OVAL_TIRE = Profile(
    name="bench_imbalanced_oval_tire",
    tones=(),
    order_tones=(
        ("wheel_1x", 1.0, (150.0, 85.0, 115.0)),
        ("wheel_2x", 1.0, (165.0, 95.0, 127.0)),
    ),
    noise_std=24.0,
    bump_probability=0.004,
    bump_decay=0.94,
    bump_strength=(30.0, 24.0, 45.0),
    modulation_hz=0.22,
    modulation_depth=0.12,
    reference_speed_kmh=DEFAULT_SPEED_KMH,
)
# An even engine tone (E2 over E1) that every sensor feels alike, 12 dB under a
# front-left imbalance at that corner. Each sensor plays one profile, so the
# tone rides on the road noise everywhere and on the imbalance at front-left,
# scaled so the sensors read it at the same level after their override gains.
_ENGINE_HUM_TONES = (("engine_2x", 1.0, (36.0, 25.0, 48.0)), ("engine_1x", 1.0, (12.0, 9.0, 18.0)))


def _with_engine_hum(base: str, gain: float) -> Profile:
    hum = tuple((key, mult, tuple(a / gain for a in amps)) for key, mult, amps in _ENGINE_HUM_TONES)
    profile = PROFILE_LIBRARY[base]
    return replace(
        profile,
        name=f"bench_{base}_engine_hum",
        order_tones=profile.order_tones + hum,
        reference_speed_kmh=DEFAULT_SPEED_KMH,
    )


_BENCH_PROFILES = {
    profile.name: profile
    for profile in (
        _ENGINE_FIRST_ORDER,
        _TIRE_OUT_OF_ROUND,
        _IMBALANCED_OVAL_TIRE,
        _with_engine_hum("rough_road", 0.28 * 0.52),
        _with_engine_hum("wheel_imbalance", 0.85),
    )
}


@pytest.fixture(autouse=True)
def _bench_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, profile in _BENCH_PROFILES.items():
        monkeypatch.setitem(PROFILE_LIBRARY, name, profile)


def _guided(
    *faults: PhaseOverride,
    top_kmh: float = 100.0,
    coast_to_kmh: float = 70.0,
    coast_s: float = 10.0,
    coast: tuple[PhaseOverride, ...] | None = None,
) -> tuple[ScenarioPhase, ...]:
    """Guided test drive: sweep up, hold, then coast down in neutral."""
    in_neutral = faults if coast is None else coast
    return (
        _phase("sweep", 8.0, 50.0, top_kmh, *faults, guided="sweep"),
        _phase("hold", 6.0, top_kmh, top_kmh, *faults, guided="hold"),
        _phase("coast", coast_s, top_kmh, coast_to_kmh, *in_neutral, guided="coast_down"),
    )


def _sweep(*faults: PhaseOverride) -> tuple[ScenarioPhase, ...]:
    """Sweep 50->115 km/h, hold 90, then a short coast to 70."""
    return (
        _phase("sweep", 12.0, 50.0, 115.0, *faults),
        _phase("hold", 6.0, 90.0, 90.0, *faults),
        _phase("coast", 4.0, 90.0, 70.0, *faults),
    )


# Held at 75-76 km/h, and the tone is there for 12 s of the 28 s drive.
_FAINT_ENGINE_REASONS = frozenset({"narrow_speed_range", "intermittent"})

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
    # Car start: the recording starts before the sensor clocks are synced, while
    # their bare device timers read within ~2 s of server time.
    Case(
        "bench-rear-right-wheel-sweep-car-start",
        _sweep(
            _ov("rear-right", "wheel_imbalance", 0.85, 1.0),
            _ov("rear-left", "wheel_mild_imbalance", 0.30, 0.55),
        ),
        _fault("wheel/tire", {"rear_right_wheel"}, "T1", dominant_corner=True),
        car_start=True,
    ),
    Case(
        "bench-rear-right-wheel-sweep-car-start-congested",
        _sweep(
            _ov("rear-right", "wheel_imbalance", 0.85, 1.0),
            _ov("rear-left", "wheel_mild_imbalance", 0.30, 0.55),
        ),
        _fault("wheel/tire", {"rear_right_wheel"}, "T1", dominant_corner=True),
        car_start=True,
        wifi_retry_loss=0.3,
    ),
    Case(
        "bench-rear-left-imbalanced-oval-sweep",
        _sweep(_ov("rear-left", _IMBALANCED_OVAL_TIRE.name, 0.85, 1.0)),
        _fault("wheel/tire", {"rear_left_wheel"}, "T1", dominant_corner=True),
    ),
    # A long neutral coast-down to 40 km/h: the imbalance fades with speed, so it
    # is seen in fewer windows than at speed, yet clearly keeps going.
    Case(
        "bench-guided-wheel-long-coastdown",
        _guided(
            _ov("front-left", "wheel_imbalance", 0.85, 1.0),
            top_kmh=110.0,
            coast_to_kmh=40.0,
            coast_s=14.0,
        ),
        _fault(
            "wheel/tire",
            {"front_left_wheel"},
            "T1",
            speed_dependence="vehicle_speed",
            dominant_corner=True,
        ),
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
    # A failing engine mount passes the engine's first order mostly into the
    # front-right corner. On the default car E1 sits on T2, so the order evidence
    # points at that wheel; the coast-down shows it stops in neutral, so it must
    # not be sent to the tire shop.
    Case(
        "bench-guided-engine-mount-front-right",
        _guided(
            _ov("all", _ENGINE_FIRST_ORDER.name, 0.25, 0.9),
            _ov("front-right", _ENGINE_FIRST_ORDER.name, 0.9, 0.9),
            coast=(_ov("all", "engine_idle", 0.2, 0.6),),
        ),
        _fault("engine", {"engine_bay"}, "E1", speed_dependence="engine_speed"),
        {
            "default": Expected(
                verdicts=frozenset({"weak_evidence"}),
                levels=WEAK_ONLY,
                speed_dependence="engine_speed",
                weak_reasons=frozenset({"coast_test_contradicts"}),
            )
        },
    ),
    # One sensor cannot compare corners: the fault is found at its corner, but
    # never as Strong.
    Case(
        "bench-one-sensor-front-left-wheel-sweep",
        _sweep(_ov("front-left", "wheel_imbalance", 0.85, 1.0)),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", levels=MODERATE),
        layout=ONE_SENSOR,
    ),
    # Sensors in the cabin only feel a wheel imbalance through the body: a wheel
    # problem, but no corner can be named and it is never Strong.
    Case(
        "bench-cabin-only-wheel-sweep",
        _sweep(_ov("body", "wheel_imbalance", 0.35, 1.0)),
        Expected(
            verdicts=frozenset({"fault", "weak_evidence"}),
            source="wheel/tire",
            zones=frozenset(sensor.location_code for sensor in CABIN_ONLY),
            order_codes=frozenset({"T1"}),
            levels=frozenset({"moderate", "weak"}),
            weak_reasons=frozenset({"spread_across_locations"}),
        ),
        layout=CABIN_ONLY,
    ),
    # One wheel sensor plus two in the cabin: the faulty wheel is the one with a
    # sensor, and it stands out from the cabin.
    Case(
        "bench-one-wheel-and-cabin-front-left-wheel-sweep",
        _sweep(
            _ov("front-left", "wheel_imbalance", 0.85, 1.0),
            _ov("body", "wheel_imbalance", 0.12, 1.0),
        ),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True),
        layout=ONE_WHEEL_AND_CABIN,
    ),
    # The same with a body that carries the imbalance well into the cabin (about
    # half the wheel's level there). The wheel corner still stands out: it is
    # that corner, not its axle, and never the engine order that on the default
    # car shares T2's frequency.
    Case(
        "bench-one-wheel-and-cabin-strong-coupling-sweep",
        _sweep(
            _ov("front-left", "wheel_imbalance", 0.85, 1.0),
            _ov("body", "wheel_imbalance", 0.45, 1.0),
        ),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True),
        layout=ONE_WHEEL_AND_CABIN,
    ),
    # A front-left imbalance with an even engine tone 12 dB under it at that
    # corner. Scoring spares the engine tone the spread penalty the wheel takes
    # (an engine is a zone), so the tone the whole car shares must not outrank
    # the imbalance. On the other car the tone costs the wheel order part of its
    # matches, so the verdict there is Moderate.
    Case(
        "bench-front-left-wheel-with-engine-hum-sweep",
        _sweep(
            _ov("all", "bench_rough_road_engine_hum", 0.28, 0.52),
            _ov("front-left", "bench_wheel_imbalance_engine_hum", 0.85, 1.0),
        ),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True),
        {
            "other": _fault(
                "wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True, levels=MODERATE
            )
        },
    ),
    # A sensor on every mounting point: road noise everywhere is still no fault,
    # and a wheel fault still stands out at its corner.
    Case("bench-healthy-sweep-every-mount", _sweep(), NO_FAULT, layout=EVERY_MOUNT),
    Case(
        "bench-front-left-wheel-sweep-every-mount",
        _sweep(_ov("front-left", "wheel_imbalance", 0.85, 1.0)),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True),
        layout=EVERY_MOUNT,
    ),
    # Idling at a standstill before pulling away (the OBD speed reads 0 km/h):
    # standing still is no speed band, and the wheel fault is still found.
    Case(
        "bench-standstill-pull-away-front-left-wheel",
        (
            _phase("idle", 8.0, 0.0, 0.0),
            _phase("pull_away", 6.0, 0.0, 50.0, _ov("front-left", "wheel_imbalance", 0.85, 1.0)),
            *_sweep(_ov("front-left", "wheel_imbalance", 0.85, 1.0)),
        ),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True),
        speed_source="obd2",
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
            weak_reasons=_FAINT_ENGINE_REASONS,
        ),
        # On the default car E1 sits on T2, so a faint engine tone may only be
        # named as a hedged guess; the run must not read as an actionable fault.
        {
            "default": Expected(
                verdicts=frozenset({"weak_evidence", "no_fault"}),
                levels=WEAK_ONLY,
                weak_reasons=_FAINT_ENGINE_REASONS,
            )
        },
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
        ("bench-rear-right-wheel-sweep", "default"),
        ("bench-cabin-only-wheel-sweep", "default"),
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
_FRAME_SAMPLES = 200  # samples per simulated DATA frame (test_support.sim_pipeline)
# A slow, one-sided sync exchange on busy Wi-Fi can step a sensor clock by up to
# half its extra delay (30 ms here).
_MAX_SYNC_STEP_US = 25_000


def injected_order_mg(
    phases: tuple[ScenarioPhase, ...],
    order_code: str,
    layout: tuple[BenchSensor, ...] = SENSORS,
) -> dict[str, float]:
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
        for index, sensor in enumerate(layout)
    ]
    injected = {sensor.location_code: 0.0 for sensor in layout}
    for phase in phases:
        apply_phase(clients, "ground-truth", phase)
        for sensor, client in zip(layout, clients, strict=True):
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


# Every case runs on one sensor-id seed in default CI; the opt-in matrix repeats
# each case over more seeds (different MACs, so different noise and clock drift).
CI_SEED = 1
MATRIX_SEEDS = (2, 3, 4, 5, 6)
MATRIX_MIN_PASSES = 4


CASE_PARAMS = [
    pytest.param(case, car_key, id=f"{case.case_id}-{car_key}")
    for case in CASES
    for car_key in sorted(CARS)
]


def _run_case(case: Case, car_key: str, seed: int, tmp_path: Path) -> None:
    car = CARS[car_key]
    result = run_sim_pipeline(
        tmp_path,
        car=car,
        sensors=case.sensors(),
        scenario_name=case.case_id,
        phases=case.phases,
        client_seed=seed,
        car_start=case.car_start,
        speed_source=case.speed_source,
    )
    try:
        lossy = bool(case.frame_loss)
        _assert_case(result, car, case.expected_for(car_key), case)
        if not case.wifi_retry_loss:
            # Congested Wi-Fi may or may not drop a frame for good.
            _assert_frame_integrity(result, lossy=lossy)
        if (case.case_id, car_key) in PDF_CASES:
            _assert_pdf_text(result, case)
    finally:
        result.history_db.close()


@pytest.mark.parametrize(("case", "car_key"), CASE_PARAMS)
def test_diagnosis_accuracy(case: Case, car_key: str, tmp_path: Path) -> None:
    _run_case(case, car_key, CI_SEED, tmp_path)


@pytest.mark.diagnostic_matrix
@pytest.mark.parametrize(("case", "car_key"), CASE_PARAMS)
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
    case: Case,
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
        _assert_order_amplitude_mg(diagnosis, case)
    if expected.speed_dependence is not None:
        assert diagnosis["speed_dependence"] == expected.speed_dependence, summary
    _assert_spectrum_markers(diagnosis, car)
    # The simulated car reports no engine RPM: an engine no-match rests on RPM
    # estimated from speed in top gear, never a plain "ruled out". The bench car's
    # references are the user's own and the simulator's speed is the true speed,
    # so wheels and driveline are ruled out outright.
    assert diagnosis["conditions"]["rpm_source"] == "estimated_top_gear"
    for check in diagnosis["source_checks"]:
        if check["status"] == "candidate" or check["reason"] in _COAST_REASONS:
            continue
        expected_check = (
            ("ruled_out_estimated", "top_gear_assumed")
            if check["source"] == "engine"
            else ("ruled_out", "no_matching_order")
        )
        assert (check["status"], check["reason"]) == expected_check, diagnosis["source_checks"]
    _assert_sensor_identity(result)
    _assert_speed_breakdown(result, case)
    _assert_raw_backed(result, case)
    _assert_raw_capture_on_one_clock(result)
    _assert_report_view(result, diagnosis, expected, case)
    if diagnosis["verdict"] == "weak_evidence":
        assert expected.weak_reasons <= set(diagnosis["weak_reasons"]), summary
        assert len(result.report.owner.reasons) == len(diagnosis["weak_reasons"]) > 0
    if diagnosis["verdict"] == "fault":
        _assert_speed_chart(result, diagnosis, case, expected)


def _assert_order_amplitude_mg(diagnosis: dict, case: Case) -> None:
    """The strongest location's mg level is on the scale of the tone the simulator injected.

    It is a median over the run's matched windows (single-axis band level, smeared
    while the speed ramps), so it reads a fraction of the injected 3-axis peak:
    about a quarter at steady speed, a few percent on fast sweeps; a unit error is
    off by 10x or more.
    """
    assert diagnosis["amplitude_basis"] == "order"
    strongest = diagnosis["location_amplitudes"][0]
    code = location_code_for_label(strongest["location"])
    injected = injected_order_mg(case.phases, diagnosis["order_code"], case.layout)[code]
    assert injected > 0, (strongest, diagnosis["order_code"])
    assert injected / 40.0 <= strongest["amplitude_mg"] <= injected / 3.0, (strongest, injected)


def injected_sweep_kmh(phases: tuple[ScenarioPhase, ...], order_code: str) -> float:
    """Widest steady speed sweep (km/h, over 8 s or more) while the order's tone was injected."""
    tone = _ORDER_TONES[order_code]
    return max(
        (
            abs(phase.speed_end_kmh - phase.speed_start_kmh)
            for phase in phases
            if phase.duration_s >= 8.0
            and any(
                (key, multiple) == tone
                for override in phase.overrides
                for key, multiple, _amps in PROFILE_LIBRARY[override.profile_name].order_tones
            )
        ),
        default=0.0,
    )


def _assert_speed_chart(
    result: SimPipelineResult, diagnosis: dict, case: Case, expected: Expected
) -> None:
    """Amplitude vs speed is charted when the fault was swept over a speed range."""
    chart = result.report.mechanic.speed_chart
    span = injected_sweep_kmh(case.phases, diagnosis["order_code"])
    if span >= 40.0:
        assert chart is not None, span
        assert [series.strongest for series in chart.series][:1] == [True]
        if expected.dominant_corner:
            # The highlighted curve is the faulty corner's, the loudest one.
            peaks = [max(amp for _speed, amp in series.points) for series in chart.series]
            assert peaks[0] == max(peaks), (chart.series[0].label, peaks)


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


def _assert_speed_breakdown(result: SimPipelineResult, case: Case) -> None:
    """The per-speed breakdown counts every moving sample and no standstill one."""
    speeds = [
        row.speed_kmh
        for batch in result.history_db.iter_run_samples(result.run_id, batch_size=2048)
        for row in batch
    ]
    standstill = sum(1 for speed in speeds if speed == 0)
    assert (standstill > 0) is case.stands_still, standstill
    breakdown = result.analysis.payload["speed_breakdown"]
    assert sum(row["count"] for row in breakdown) == len(speeds) - standstill, breakdown


def _assert_frame_integrity(result: SimPipelineResult, *, lossy: bool) -> None:
    """Frame integrity warns on lost frames and on raw replay that did not cover the run.

    It never reads "no sensor data was lost" next to the replay-coverage warning.
    """
    checks = {check.label: check for check in result.report.quality.checks}
    frame_integrity = checks["Frame integrity"]
    codes = {warning["code"] for warning in result.analysis.payload["warnings"]}
    incomplete = lossy or "raw_replay_coverage_incomplete" in codes
    assert frame_integrity.passed is not incomplete, frame_integrity
    assert frame_integrity.state == ("Check" if incomplete else "OK"), frame_integrity
    if lossy:
        assert "dropped frames" in frame_integrity.detail
    elif incomplete:
        assert "The raw capture did not cover the whole run" in frame_integrity.detail
    if incomplete:
        assert not result.report.quality.all_passed


def _assert_raw_capture_on_one_clock(result: SimPipelineResult) -> None:
    """Each sensor's raw chunks sit on its own continuous sample clock.

    The simulated sensors sample without pause, so consecutive raw chunks are a
    whole number of frames apart (more than one where frames were lost), give or
    take a clock-sync correction. A chunk stamped on another clock (bare device
    time, seconds off at car start) breaks that.
    """
    capture = result.history_db.load_raw_capture(result.run_id)
    assert capture is not None
    for sensor in capture.sensors:
        frame_us = 1_000_000.0 * _FRAME_SAMPLES / sensor.manifest.sample_rate_hz
        starts = sorted(chunk.t0_us for chunk in sensor.chunks)
        for previous, current in zip(starts, starts[1:], strict=False):
            frames = (current - previous) / frame_us
            off_us = abs(frames - round(frames)) * frame_us
            assert round(frames) >= 1 and off_us < _MAX_SYNC_STEP_US, (
                sensor.manifest.client_id,
                previous,
                current,
            )


def _assert_raw_backed(result: SimPipelineResult, case: Case) -> None:
    """Analysis replays the raw capture wherever the sensor clocks were synced.

    On a clean network every recorded row is replayed from raw samples (rows
    whose spectrum reaches back before the start are not recorded at all).
    """
    metadata = result.analysis.payload["analysis_metadata"]
    assert isinstance(metadata, dict)
    raw_backed, total = metadata["raw_backed_sample_count"], metadata["total_sample_count"]
    assert isinstance(raw_backed, int) and isinstance(total, int)
    if case.clean_network:
        assert metadata["raw_capture_mode"] == "raw_backed", metadata
        assert raw_backed == total, metadata
    assert metadata["raw_capture_mode"] in {"raw_backed", "partial_raw_backed"}, metadata
    if case.frame_loss:
        # The lossy sensor's frame gaps leave its rows to the stored summaries.
        assert raw_backed >= 0.6 * total, metadata
        return
    if case.car_start:
        # Chunks stamped on bare device time before the sync are not captured, so
        # each sensor's raw timeline starts at its first synced chunk; only the
        # first seconds (sync plus one FFT window) replay from the summaries.
        assert raw_backed >= 0.6 * total, metadata
    else:
        assert raw_backed >= 0.85 * total, metadata
    assert metadata["raw_replay_sample_rate_unverified_sensor_count"] == 0
    assert metadata["raw_replay_timing_fallback_count"] == 0


_ENGINE_TOP_GEAR_LINE = (
    "Engine: no match with the engine orders estimated for top gear; lower gears were not checked"
)
_COAST_REASONS = ("stayed_in_neutral", "stopped_in_neutral")
_SPEED_SOURCE_TEXT = {"gps": "GPS", "obd2": "OBD"}
_SOURCE_NAMES_EN = {"wheel/tire": "Wheels/tires", "driveline": "Driveline", "engine": "Engine"}

# What the owner is told to have checked, per diagnosed order.
_NEXT_STEP_KEYWORDS = {"T1": "balanced", "T2": "out-of-round", "P1": "propshaft", "E2": "mounts"}


def _assert_report_view(
    result: SimPipelineResult, diagnosis: dict, expected: Expected, case: Case
) -> None:
    # The mechanic's worksheet lists each order once; where it was strongest is
    # in the per-location table.
    worksheet_orders = [row.order for row in result.report.mechanic.worksheet]
    assert len(worksheet_orders) == len(set(worksheet_orders)), worksheet_orders
    owner = result.report.owner
    assert owner.verdict == diagnosis["verdict"]
    assert owner.level == diagnosis["confidence_level"]
    conditions = {fact.label: fact.value for fact in result.report.mechanic.conditions}
    assert conditions["Speed source"] == _SPEED_SOURCE_TEXT[case.speed_source], conditions
    engine_check = next(c for c in diagnosis["source_checks"] if c["source"] == "engine")
    if engine_check["reason"] == "top_gear_assumed":
        # The workshop is told the engine check assumed top gear.
        assert _ENGINE_TOP_GEAR_LINE in result.report.mechanic.ruled_out
    if diagnosis["verdict"] == "no_fault":
        assert owner.headline == "No significant vibration found"
        assert owner.diagram.zone is None
        # What the drive did not cover: the simulator reports no engine RPM, so the
        # engine was untested or checked in top gear only, and a drive that never
        # went below 40 km/h says so.
        not_covered = owner.not_covered
        assert any(item.startswith("Engine: ") for item in not_covered), not_covered
        lowest_kmh = min(min(p.speed_start_kmh, p.speed_end_kmh) for p in case.phases)
        below = any(item.startswith("Speeds below") for item in not_covered)
        assert below is (lowest_kmh >= 40.0), not_covered
        return
    cause_text = owner.headline if diagnosis["verdict"] == "fault" else owner.candidate
    assert cause_text is not None
    zone_text = _ZONE_TEXT_EN.get(diagnosis["zone"])
    if zone_text is not None:
        assert zone_text in cause_text, cause_text
    unlocated_wheel = diagnosis["source"] == "wheel/tire" and not case.wheel_sensors
    if unlocated_wheel:
        not_pinned, felt_at, mount_sensors = _UNLOCATED_WHEEL_TEXT["en"]
        assert not_pinned in cause_text, cause_text
        assert felt_at.format(_CABIN_TEXT[diagnosis["zone"]][0]) in cause_text, cause_text
        advice = owner.next_step if diagnosis["verdict"] == "fault" else " ".join(owner.recapture)
        assert mount_sensors in advice, advice
    assert owner.diagram.zone == diagnosis["zone"]
    level_words = {"strong": "Strong", "moderate": "Moderate", "weak": "Weak"}
    assert owner.level_word == level_words[diagnosis["confidence_level"]]
    # Page 2 marks the diagnosed order at the level page 1 gives it.
    diagnosed_levels = [row.level for row in result.report.mechanic.worksheet if row.diagnosed]
    assert diagnosed_levels == [owner.level_word], diagnosed_levels
    if (diagnosis["zone"], diagnosis["confidence_level"]) == ("all_wheels", "moderate") and (
        diagnosis["speed_dependence"] is None
    ):
        # Swapping axles moves nothing when all four wheels carry it.
        assert owner.confirm is not None and "coast" in owner.confirm, owner.confirm
    rows = [row for row in diagnosis["location_amplitudes"] if row["amplitude_mg"] is not None]
    strongest = [marker for marker in owner.diagram.markers if marker.strongest]
    assert len(strongest) == 1 and rows
    assert strongest[0].value.endswith(" mg")
    if diagnosis["verdict"] == "fault":
        # The diagnosed source is never listed among the sources ruled out.
        source_name = _SOURCE_NAMES_EN.get(diagnosis["source"])
        ruled_out = result.report.mechanic.ruled_out
        assert not any(line.startswith(f"{source_name}:") for line in ruled_out), ruled_out
        assert owner.verify is not None
        assert f"{diagnosis['order_code']} " in owner.verify
        assert owner.verify.rstrip(".").endswith("mg today")
        keyword = _NEXT_STEP_KEYWORDS.get(diagnosis["order_code"])
        if keyword is not None and not unlocated_wheel:
            assert keyword in owner.next_step, owner.next_step
    if expected.dominant_corner and diagnosis["verdict"] == "fault":
        corner = _ZONE_TEXT_EN[diagnosis["zone"]]
        assert f"stronger at the {corner} than at the next sensor" in owner.description, (
            owner.description
        )


def _assert_pdf_text(result: SimPipelineResult, case: Case) -> None:
    verdict = result.diagnosis["verdict"]
    unlocated_wheel = result.diagnosis["source"] == "wheel/tire" and not case.wheel_sensors
    for lang, headline in zip(("en", "nl"), _PDF_HEADLINES[verdict], strict=True):
        view = build_report_view(result.analysis.payload, result.metadata, lang=lang)
        reader = PdfReader(io.BytesIO(render_report_pdf(view)))
        pages = [" ".join((page.extract_text() or "").split()).lower() for page in reader.pages]
        assert len(pages) >= 2
        assert headline in pages[0], pages[0][:300]
        # Dutch reports write decimals with a comma (2,9 mg), English with a point.
        decimal_mg = re.compile(r"\d([.,])\d\s?mg")
        assert {match.group(1) for page in pages for match in decimal_mg.finditer(page)} <= (
            {","} if lang == "nl" else {"."}
        )
        # Levels only, never a confidence percentage (page 1 is the owner page).
        assert "%" not in pages[0]
        if unlocated_wheel:
            not_pinned, felt_at, mount_sensors = _UNLOCATED_WHEEL_TEXT[lang]
            felt_where = _CABIN_TEXT[result.diagnosis["zone"]][lang == "nl"]
            for text in (not_pinned, felt_at.format(felt_where), mount_sensors):
                assert text in pages[0], (text, pages[0][:400])
        if verdict == "fault":
            assert view.owner.next_step.lower()[:40] in pages[0]
            assert view.owner.verify is not None
        workshop = " ".join(pages[1:])
        for chart in (view.mechanic.spectrum, view.mechanic.speed_chart):
            if chart is not None:
                # PDF text extraction turns the non-breaking space before units into a space.
                assert " ".join(chart.title.lower().split()) in workshop, chart.title


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


def test_recording_stops_at_the_configured_cap_and_is_still_analysed(tmp_path: Path) -> None:
    fault = _ov("front-left", "wheel_imbalance", 0.85, 1.0)
    phases = (*_sweep(fault), _phase("cruise", 13.0, 70.0, 70.0, fault))
    assert sum(phase.duration_s for phase in phases) == 35.0
    result = run_sim_pipeline(
        tmp_path,
        car=DEFAULT_CAR,
        sensors=SENSORS,
        scenario_name="capped-drive",
        phases=phases,
        client_seed=CI_SEED,
        max_recording_duration_s=20.0,
    )
    try:
        assert result.stop_reason == "max_duration"
        assert result.analysis.payload["duration_s"] == pytest.approx(20.0, abs=1.0)
        diagnosis = result.diagnosis
        assert (diagnosis["verdict"], diagnosis["source"], diagnosis["zone"]) == (
            "fault",
            "wheel/tire",
            "front_left_wheel",
        )
    finally:
        result.history_db.close()
