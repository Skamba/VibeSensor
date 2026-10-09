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
import itertools
import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

import pytest
from pypdf import PdfReader
from test_support.report_rendering import (
    propshaft_mentions,
    report_view_texts,
    wheel_speed_part_mentions,
)
from test_support.sim_pipeline import (
    SENSORS_RUN_BEFORE_DRIVE_S,
    BenchCar,
    BenchSensor,
    SimPipelineResult,
    SpeedSource,
    run_sim_pipeline,
)

from vibesensor.analysis.constants import MIN_ANALYSIS_FREQ_HZ
from vibesensor.analysis.felt_ranking import FELT_LOCATIONS
from vibesensor.analysis.phase_segmentation import DrivingPhase, segment_run_phases
from vibesensor.domain.engine_profile import EngineProfile
from vibesensor.domain.locations import location_code_for_label, wheel_axle
from vibesensor.recording.run_schema import GuidedPhaseName
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.report.i18n import tr
from vibesensor.report.pdf import render_report_pdf
from vibesensor.report.view_model import build_report_view
from vibesensor.simulator.confounders import AccessoryTone, FlatSpot, MountSlip, SensorFixing
from vibesensor.simulator.fault_forces import OrderForce
from vibesensor.simulator.profiles import (
    DEFAULT_SPEED_KMH,
    PROFILE_LIBRARY,
    ROAD_RESONANCES,
    Profile,
    RoadResonance,
)
from vibesensor.simulator.road_surface import generated_road
from vibesensor.simulator.scripted_scenario_catalog import SCRIPTED_SCENARIOS
from vibesensor.simulator.scripted_scenario_models import PhaseOverride, PhasePulse, ScenarioPhase
from vibesensor.simulator.scripted_targeting import apply_phase
from vibesensor.simulator.sim_client import SimClient, make_client_id

DEFAULT_CAR = BenchCar("Default car", 285.0, 30.0, 21.0, 3.08, 0.64)
# 3.4 x 0.8: engine orders fall between the wheel orders instead of on T2.
OTHER_CAR = BenchCar("Hatchback", 205.0, 55.0, 16.0, 3.4, 0.8)
# A battery-electric hatchback: no gearbox, its motor turns at wheel speed x 9.0.
EV_CAR = BenchCar("Electric hatchback", 215.0, 50.0, 18.0, 9.0, 1.0, fuel_type="EV")
# The same EV entered without its reduction ratio.
EV_NO_RATIO_CAR = replace(EV_CAR, final_drive_entered=False)
# The same cars with their drive layout given: a front-wheel-drive hatchback has
# no propshaft; the rear- and all-wheel-drive saloons carry one to the rear axle.
FWD_CAR = replace(OTHER_CAR, name="FWD hatchback", drive_layout="FWD")
RWD_CAR = replace(DEFAULT_CAR, name="RWD saloon", drive_layout="RWD")
AWD_CAR = replace(DEFAULT_CAR, name="AWD saloon", drive_layout="AWD")
# A rear-wheel-drive saloon with an inline-six and an 8-speed automatic:
# 225/45 R18 tires, final drive 3.15, top gear 0.67. The six fires three times
# per crank turn (E3), 6.33 times per wheel turn in top gear: on P2 (6.30).
INLINE_6_CAR = BenchCar(
    "Inline-6 RWD saloon",
    225.0,
    45.0,
    18.0,
    3.15,
    0.67,
    fuel_type="ICE",
    drive_layout="RWD",
    engine_profile=EngineProfile("inline", 6),
)
# Its 5th to 8th gears; 6th is direct (1:1), where E1 is P1.
_FIFTH_OF_8, _SIXTH_OF_8, _SEVENTH_OF_8, _EIGHTH_OF_8 = 1.32, 1.00, 0.84, 0.67
# The other car's ratios with a known engine: an inline-3 fires at E1.5, an
# inline-4 at E2, a V8 at E4, none of them on a wheel or propshaft order.
INLINE_3_CAR = replace(
    OTHER_CAR, name="Inline-3 hatchback", fuel_type="ICE", engine_profile=EngineProfile("inline", 3)
)
INLINE_4_CAR = replace(
    OTHER_CAR, name="Inline-4 hatchback", fuel_type="ICE", engine_profile=EngineProfile("inline", 4)
)
V8_CAR = replace(OTHER_CAR, name="V8 coupe", fuel_type="ICE", engine_profile=EngineProfile("v", 8))
# Staggered tires: 235/35 R19 at the front, 265/35 R19 at the rear. The front
# tires are 3 % smaller, so the front wheels turn 3 % faster at one road speed.
STAGGERED_CAR = replace(
    DEFAULT_CAR,
    name="Staggered RWD coupe",
    tire_width_mm=265.0,
    tire_aspect_pct=35.0,
    rim_in=19.0,
    drive_layout="RWD",
    front_tire=(235.0, 35.0, 19.0),
)
CARS = {
    "default": DEFAULT_CAR,
    "other": OTHER_CAR,
    "ev": EV_CAR,
    "ev_no_ratio": EV_NO_RATIO_CAR,
    "fwd": FWD_CAR,
    "rwd": RWD_CAR,
    "awd": AWD_CAR,
    "inline_6": INLINE_6_CAR,
    "inline_3": INLINE_3_CAR,
    "inline_4": INLINE_4_CAR,
    "v8": V8_CAR,
    "staggered": STAGGERED_CAR,
}
# Every case runs on these two cars unless it names its own.
BOTH_CARS = ("default", "other")

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
# The wheel sensors plus one on the engine.
WITH_ENGINE_BAY = (*SENSORS, BenchSensor("VS-70 engine", "engine_bay"))

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
MODERATE_OR_STRONG = frozenset({"strong", "moderate"})

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
_SPREAD_WHEEL_ZONES = frozenset({"front_axle", "rear_axle", "all_wheels"})
_WHEEL_AXLE_TEXT_EN = {"front_axle": "front wheels", "rear_axle": "rear wheels"}
_CABIN_TEXT = {
    "driver_seat": ("driver seat", "bestuurdersstoel"),
    "trunk": ("trunk", "kofferbak"),
    "front_passenger_seat": ("front passenger seat", "bijrijdersstoel"),
}
# A wheel fault felt only in the cabin, or at the only wheel with a sensor: no
# wheel named, and the owner is told to put sensors at the wheels to find it.
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
_ONLY_WHEEL_SENSOR_TEXT = {
    "en": "only the front-left wheel had a sensor",
    "nl": "alleen het wiel linksvoor had een sensor",
}


@dataclass(frozen=True, slots=True)
class Expected:
    """Ground truth for one scenario, from what the scenario injects."""

    verdicts: frozenset[str]
    source: str | None = None
    # ``None``: no zone can be named (one wheel sensor feels every wheel).
    zones: frozenset[str | None] = frozenset()
    order_codes: frozenset[str] = frozenset()
    levels: frozenset[str] = STRONG
    speed_dependence: str | None = None
    # One corner carries the fault well above the others (single-wheel faults).
    dominant_corner: bool = False
    # The driving phase the fault shows up in (brake judder: only while braking).
    dominant_phase: str | None = None
    # What a weak-evidence report must say made the run hard to judge.
    weak_reasons: frozenset[str] = frozenset()
    # The speed band (km/h) where the injected order shakes hardest.
    peak_speed_kmh: tuple[float, float] | None = None
    # A strong vibration no checked order explains: a no-fault report must say
    # it was there, never that nothing significant was found.
    unexplained_vibration: bool = False


class IdealisedFloor(Enum):
    """Why a case drives on the idealised white-noise floor instead of the road.

    Every other case drives on ``generated_road(seed)``: every real car has a
    road under it. These expectations the analysis does not meet on that road
    yet, for reasons that need a product decision, not a simulator or test
    change ("Benchmark on the realistic road" in docs/simulator_realism.md).
    """

    # A mild or faint order (wheel, brake judder, engine) under the knuckles'
    # wheel-hop hump is missed: each window's strongest peaks are the hump's.
    MISSED_UNDER_WHEEL_HOP = "missed under the wheel-hop hump"
    # At town speeds the wheel order runs through the hump at every corner: a
    # healthy car reads a weak or moderate wheel or brake fault, and a faulty
    # corner reads spread over all four.
    HUMP_MATCHES_IN_TOWN = "the hump matches the wheel order in town"
    # A clear fault reads a confidence level lower: the hump's matches at the
    # other corners count as evidence spread over them.
    LEVEL_UNDER_THE_HUMP = "one confidence level lower"
    # On more than one seed in five the hump moves what the report names: the
    # wheel order's second harmonic, another corner, one of two equal corners
    # alone, a level over the injected tone's, or a healthy car's fault.
    HUMP_SCATTER = "the named order, corner or level moves between seeds"
    # The case checks the unexplained-vibration wording, which needs a body
    # mode over its 26 dB bar: on the road this fixed-amplitude 13 Hz mode
    # stands 23 dB over the trunk's floor.
    UNEXPLAINED_BAR = "the body mode is under the unexplained-vibration bar"


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
    # The other right answer when the drive carries two real faults.
    second_fault: Expected | None = None
    # The cars the drive runs on.
    cars: tuple[str, ...] = BOTH_CARS
    # The OBD adapter also reads the engine RPM (needs ``speed_source="obd2"``).
    obd_rpm: bool = False
    # The speed source reports every ``speed_report_period_s`` the speed it
    # measured ``speed_lag_s`` earlier (a GPS receiver: once a second, late).
    speed_lag_s: float = 0.0
    speed_report_period_s: float = 0.5
    # How far the OBD speed (the speedometer's) reads over the true speed (0.03: 3 %).
    obd_speed_over_read: float = 0.0
    # Guided steps the driver taps through without driving them: the report
    # lists them as tapped but not detected, never as done.
    guided_undetected: tuple[GuidedPhaseName, ...] = ()
    # How each location's sensor is fixed, when not firmly (a loose one rattles).
    fixings: dict[str, SensorFixing] = field(default_factory=dict)
    # The parking flat spots each location's sensor feels at the start of the drive.
    flat_spots: dict[str, FlatSpot] = field(default_factory=dict)
    # Accessories each location's sensor feels running.
    accessories: dict[str, tuple[AccessoryTone, ...]] = field(default_factory=dict)
    # How each location's sensor turns on its fixing, when it does.
    slips: dict[str, MountSlip] = field(default_factory=dict)
    # The locations whose sensor turns on its fixing between steady stretches of
    # the drive: the report must say it may be loose.
    loose_mounts: frozenset[str] = frozenset()
    # Why the drive runs on the idealised white-noise floor; ``None``: on a
    # generated ISO 8608 road through a quarter car and the ADXL345 front end
    # (``docs/simulator_realism.md``), as every real car drives.
    idealised_floor: IdealisedFloor | None = None
    # Why the case runs only with physical fault amplitudes (``FAULT_AMPLITUDES``).
    physical_only: str | None = None

    def sensors(self) -> tuple[BenchSensor, ...]:
        return tuple(
            replace(
                sensor,
                frame_loss=self.frame_loss.get(sensor.location_code, 0.0),
                uplink_latency_spike_s=self.uplink_latency_spike_s,
                wifi_retry_loss=self.wifi_retry_loss,
                fixing=self.fixings.get(sensor.location_code),
                slip=self.slips.get(sensor.location_code),
                flat_spot=self.flat_spots.get(sensor.location_code),
                accessories=self.accessories.get(sensor.location_code, ()),
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

    def expected_for(self, car: str, diagnosed_source: str | None) -> Expected:
        if self.second_fault is not None and diagnosed_source == self.second_fault.source:
            return self.second_fault
        return self.by_car.get(car, self.expected)

    @property
    def wheels(self) -> set[str]:
        """The wheel corners with a sensor."""
        return {sensor.location_code for sensor in self.layout} & WHEEL_ZONES

    @property
    def corners_compared(self) -> bool:
        """Sensors at two or more wheels: a corner can be told from another."""
        return len(self.wheels) >= 2

    @property
    def axles_compared(self) -> bool:
        """Wheel sensors on both axles: an axle can be told from the other."""
        return len({corner.split("_", 1)[0] for corner in self.wheels}) == 2

    @property
    def stands_still(self) -> bool:
        return any(phase.speed_start_kmh == 0 == phase.speed_end_kmh for phase in self.phases)

    @property
    def brakes_firmly(self) -> bool:
        """The drive brakes from speed: a phase sheds 0.25 g or more for 3 s or more above 30 km/h.

        A car coasting without the brakes slows at well under 0.15 g, and a stop
        from town speeds is over too soon to judge a judder.
        """
        return any(_brakes_firmly(phase) for phase in self.phases)

    @property
    def guided_steps(self) -> list[str]:
        """The guided test-drive steps the drive marks, each once, in order."""
        return list(dict.fromkeys(p.guided_phase for p in self.phases if p.guided_phase))

    @property
    def guided_firm_stops(self) -> int:
        """The firm stops the driver makes in the guided brake step."""
        return sum(p.guided_phase == "brake" and _brakes_firmly(p) for p in self.phases)


def _brakes_firmly(phase: ScenarioPhase) -> bool:
    return (
        phase.speed_start_kmh - phase.speed_end_kmh
    ) / 3.6 / phase.duration_s >= _FIRM_BRAKING_MPS2 and _seconds_above(
        phase, _FIRM_BRAKING_FROM_KMH
    ) >= 3.0


def _fault(source: str, zones: set[str | None], order: str, **kwargs: object) -> Expected:
    return Expected(
        verdicts=frozenset({"fault"}),
        source=source,
        zones=frozenset(zones),
        order_codes=frozenset({order}),
        **kwargs,  # type: ignore[arg-type]
    )


NO_FAULT = Expected(verdicts=frozenset({"no_fault"}), levels=frozenset())
_FIRM_BRAKING_MPS2 = 0.25 * 9.81
_FIRM_BRAKING_FROM_KMH = 30.0


def _seconds_above(phase: ScenarioPhase, kmh: float) -> float:
    """How long a slowing phase stays above *kmh*."""
    start, end = phase.speed_start_kmh, phase.speed_end_kmh
    if start <= end or start <= kmh:
        return 0.0
    return (start - max(end, kmh)) / (start - end) * phase.duration_s


def _scripted(
    name: str,
    expected: Expected,
    *,
    idealised_floor: IdealisedFloor | None = None,
    **by_car: Expected,
) -> Case:
    return Case(
        name,
        SCRIPTED_SCENARIOS[name].phases,
        expected,
        dict(by_car),
        idealised_floor=idealised_floor,
    )


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
    gear: float | None = None,
    turn_radius_m: float | None = None,
    grade_pct: float = 0.0,
) -> ScenarioPhase:
    return ScenarioPhase(
        name=name,
        duration_s=duration_s,
        speed_start_kmh=start,
        speed_end_kmh=end,
        overrides=(_ROAD, *ovs),
        guided_phase=guided,
        gear_ratio=gear,
        turn_radius_m=turn_radius_m,
        grade_pct=grade_pct,
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


def _engine_firing(name: str, *tones: tuple[float, tuple[float, float, float]]) -> Profile:
    """The engine_order profile's sound at the crank orders *tones* ``(multiple, amps_xyz)``."""
    return replace(
        PROFILE_LIBRARY["engine_order"],
        name=f"bench_{name}",
        order_tones=tuple(("engine_1x", multiple, amps) for multiple, amps in tones),
    )


# A rough-running six or worn engine mounts: the firing rhythm (E3) shakes the car.
_SIX_FIRING = _engine_firing("six_firing", (3.0, (185.0, 128.0, 248.0)))
# An inline-3's firing rhythm (E1.5) over its built-in rocking couple (E1).
_THREE_FIRING = _engine_firing(
    "three_firing", (1.5, (185.0, 128.0, 248.0)), (1.0, (62.0, 46.0, 92.0))
)
# A V8's firing rhythm (E4).
_V8_FIRING = _engine_firing("v8_firing", (4.0, (185.0, 128.0, 248.0)))
# A propshaft joint working at an angle: twice per shaft turn (P2) dominates.
_PROPSHAFT_JOINT = replace(
    PROFILE_LIBRARY["driveshaft_imbalance"],
    name="bench_propshaft_joint",
    order_tones=(("shaft_1x", 2.0, (150.0, 120.0, 190.0)), ("shaft_1x", 1.0, (45.0, 36.0, 60.0))),
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


# Brake judder: a brake disc with thickness variation or runout pulses the brake
# torque once per wheel turn, so the wheel's first order shows up while braking
# and only then.
_BRAKE_JUDDER = Profile(
    name="bench_brake_judder",
    tones=(),
    order_tones=(("wheel_1x", 1.0, (220.0, 125.0, 170.0)),),
    noise_std=24.0,
    bump_probability=0.004,
    bump_decay=0.94,
    bump_strength=(30.0, 24.0, 45.0),
    modulation_hz=0.22,
    modulation_depth=0.12,
    reference_speed_kmh=DEFAULT_SPEED_KMH,
)

# -- realistic cars: layered sensor signals --------------------------------------
# Each sensor plays one profile, so a sensor that hears several things at once
# (road noise, its own wheel, a neighbour's wheel, a body resonance) plays a
# layered profile under the road override's gains: the road reads as on every
# other sensor and each layer at the level its gain gives it on its own.
_ROAD_SCENE_GAIN, _ROAD_AMP = 0.28, 0.52
_ROAD_GAIN = _ROAD_SCENE_GAIN * _ROAD_AMP
# Tire and road noise grow with speed (about in proportion), unlike the flat
# road noise the scripted scenarios play.
_ROAD_NOISE_SPEED_EXPONENT = 1.0


_LAYERED_PROFILES: dict[str, Profile] = {}


@dataclass(frozen=True, slots=True)
class _Layer:
    """The order tones of a simulator profile at *gain*, at *hz_scale* times their frequency.

    A wheel on a tire 0.5 % smaller turns 0.5 % faster (``hz_scale`` 1.005).
    """

    profile: str
    gain: float
    hz_scale: float = 1.0


def _road_with(
    name: str,
    *layers: _Layer,
    forces: tuple[OrderForce, ...] = (),
    resonance: tuple[float, float] | None = None,
    **speed_laws: object,
) -> Profile:
    """Road noise that grows with speed, plus *layers*, *forces* and a fixed *resonance*.

    The resonance ``(hz, gain)`` is a body or seat mode: the engine-idle
    profile's 13 Hz shake at *gain*, moved to *hz*.
    """
    road = PROFILE_LIBRARY["rough_road"]
    order_tones = tuple(
        (key, multiple * layer.hz_scale, tuple(a * layer.gain / _ROAD_GAIN for a in amps))
        for layer in layers
        for key, multiple, amps in PROFILE_LIBRARY[layer.profile].order_tones
    )
    tones: tuple[tuple[float, tuple[float, float, float]], ...] = ()
    if resonance is not None:
        hz, gain = resonance
        idle_amps = PROFILE_LIBRARY["engine_idle"].tones[0][1]
        tones = ((hz, tuple(a * gain / _ROAD_GAIN for a in idle_amps)),)  # type: ignore[assignment]
    profile = replace(
        road,
        name=f"bench_{name}",
        tones=tones,
        order_tones=order_tones,  # type: ignore[arg-type]
        reference_speed_kmh=DEFAULT_SPEED_KMH if order_tones else None,
        order_forces=tuple(force.scaled(1.0 / _ROAD_GAIN) for force in forces),
        noise_speed_exponent=_ROAD_NOISE_SPEED_EXPONENT,
        order_speed_exponent=max(
            (PROFILE_LIBRARY[layer.profile].order_speed_exponent for layer in layers), default=0.0
        ),
        **speed_laws,  # type: ignore[arg-type]
    )
    assert _LAYERED_PROFILES.setdefault(profile.name, profile) == profile, profile.name
    return profile


def _on(target: str, profile: Profile, coupling: float = 1.0) -> PhaseOverride:
    """*target* plays *profile* under the road's gains; *coupling* scales all it hears."""
    return _ov(target, profile.name, _ROAD_SCENE_GAIN, _ROAD_AMP * coupling)


# -- fault amplitudes: tuned or physical ----------------------------------------
# Each fault comes in two sizes. Tuned (the default, what CI gates on): order
# tones at levels set per sensor, sized so the analysis finds what a real car
# with that fault shows. Physical (VIBESENSOR_BENCH_FAULT_AMPLITUDES=physical):
# the fault as a force in the car, in grams or newtons, which every sensor
# reads through the car to its own mount (``simulator/fault_forces.py``): a
# measured yardstick, not a gate (``tools/dev/physical_fault_tally.py``). The
# basis of each size is in "Fault amplitudes" in docs/simulator_realism.md.


class FaultAmplitudes(Enum):
    TUNED = "tuned"
    PHYSICAL = "physical"


FAULT_AMPLITUDES = FaultAmplitudes(os.environ.get("VIBESENSOR_BENCH_FAULT_AMPLITUDES", "tuned"))


def _sized(
    tuned: tuple[PhaseOverride, ...], physical: tuple[PhaseOverride, ...]
) -> tuple[PhaseOverride, ...]:
    """The fault's *tuned* overrides, or its *physical* ones (see FAULT_AMPLITUDES)."""
    return physical if FAULT_AMPLITUDES is FaultAmplitudes.PHYSICAL else tuned


# A wheel that lost a balancing weight, or was fitted unbalanced: 40 g at the rim.
_LOST_WEIGHT_G = 40.0
# A wheel noticeably but mildly out of balance.
_MILD_G = 15.0
# A wheel a little out of balance, felt only at motorway speed.
_WEAK_G = 10.0
# The balancing tolerance: a balancer shows under 5 g (a quarter ounce) as zero.
_BARELY_THERE_G = 5.0
# A propshaft that lost a balance weight: 15 g on its 40 mm tube radius.
_PROPSHAFT_RADIUS_M = 0.04
_PROPSHAFT_IMBALANCE_FORCES = (
    OrderForce("shaft_1x", unbalance_g=15.0, radius_m=_PROPSHAFT_RADIUS_M),
)
# An inline-4 without (or with a failed) balance shaft: its pistons'
# second-order free force (0.5 kg reciprocating per cylinder, 45 mm crank
# radius, 0.3 crank-to-rod ratio) as an unbalance turning at twice the crank
# speed (E2), over the crankshaft and flywheel's residual unbalance at E1,
# balanced four times worse than ISO 21940-11 G6.3.
_CRANK_RADIUS_M, _FLYWHEEL_RADIUS_M = 0.045, 0.1
_I4_SECOND_ORDER_FORCES = (
    OrderForce("engine_2x", unbalance_g=150.0, radius_m=_CRANK_RADIUS_M),
    OrderForce("engine_1x", unbalance_g=20.0, radius_m=_FLYWHEEL_RADIUS_M),
)
# The simulator's fault profiles with the physical sizes, for the scripted
# scenarios that play them.
_PHYSICAL_LIBRARY = {
    name: replace(
        PROFILE_LIBRARY[name],
        order_tones=(),
        reference_speed_kmh=None,
        order_speed_exponent=0.0,
        order_forces=forces,
    )
    for name, forces in (
        ("wheel_imbalance", (OrderForce("wheel_1x", unbalance_g=_LOST_WEIGHT_G),)),
        ("wheel_mild_imbalance", (OrderForce("wheel_1x", unbalance_g=_MILD_G),)),
        ("driveshaft_imbalance", _PROPSHAFT_IMBALANCE_FORCES),
        ("engine_order", _I4_SECOND_ORDER_FORCES),
    )
}
# An engine whose first order dominates: a flywheel or crank pulley out by
# 50 g at 0.1 m (25 times ISO 21940-11 G6.3).
_ENGINE_FIRST_ORDER_FORCES = (
    OrderForce("engine_1x", unbalance_g=50.0, radius_m=_FLYWHEEL_RADIUS_M),
)
# An engine's firing pulses rock it on its mounts: about 150 N·m of torque at
# the firing order (about the mean torque at part load), reacted by mounts
# about 0.3 m apart, so about 500 N at each, the same at every speed.
_FIRING_FORCE_N = 500.0
_SIX_FIRING_FORCES = (OrderForce("engine_1x", 3.0, force_n=_FIRING_FORCE_N),)
# An inline-3's firing rhythm over the rocking couple its counterweights leave
# at E1 (about 60 g at the crank radius at the mounts).
_THREE_FIRING_FORCES = (
    OrderForce("engine_1x", 1.5, force_n=_FIRING_FORCE_N),
    OrderForce("engine_1x", unbalance_g=60.0, radius_m=_CRANK_RADIUS_M),
)
_V8_FIRING_FORCES = (OrderForce("engine_1x", 4.0, force_n=_FIRING_FORCE_N),)
# An even engine hum (E2 over E1): an inline-4 whose balance shafts cancel
# most of its second-order force (about 20 g at the crank radius left) and a
# crankshaft balanced to G6.3 (5 g at 0.1 m).
_ENGINE_HUM_FORCES = (
    OrderForce("engine_2x", unbalance_g=20.0, radius_m=_CRANK_RADIUS_M),
    OrderForce("engine_1x", unbalance_g=5.0, radius_m=_FLYWHEEL_RADIUS_M),
)
# A propshaft joint working at too steep an angle pulses the shaft's torque
# twice per turn (P2): about 30 N at its bearings, over a 5 g residual at P1.
_PROPSHAFT_JOINT_FORCES = (
    OrderForce("shaft_1x", 2.0, force_n=30.0),
    OrderForce("shaft_1x", unbalance_g=5.0, radius_m=_PROPSHAFT_RADIUS_M),
)
# A tyre's radial force variation (non-uniform stiffness or runout) is a force
# its shape fixes, the same at every speed: an OEM tyre passes uniformity
# grading under about 100 N at the first harmonic (Gent & Walter, *The
# Pneumatic Tire*, NHTSA 2006, ch. 9); a faulty one is well over. It pushes up
# through the contact patch.
_RFV_FAULT_N = 150.0
_RADIAL = (0.0, 0.0, 1.0)
# An out-of-round tyre: twice per wheel turn dominates.
_TIRE_OUT_OF_ROUND_FORCES = (
    OrderForce("wheel_2x", force_n=_RFV_FAULT_N, direction=_RADIAL),
    OrderForce("wheel_1x", force_n=_RFV_FAULT_N / 3.0, direction=_RADIAL),
)
# An unbalanced tyre that is also oval: once and twice per turn about equally strong.
_IMBALANCED_OVAL_TIRE_FORCES = (
    OrderForce("wheel_1x", unbalance_g=30.0),
    OrderForce("wheel_2x", force_n=_RFV_FAULT_N / 2.0, direction=_RADIAL),
)
# Radial force variation at the first four wheel orders, falling off about as 1/n.
_NON_UNIFORM_TYRE_FORCES = tuple(
    OrderForce("wheel_1x", float(n), force_n=_RFV_FAULT_N / n, direction=_RADIAL)
    for n in (1, 2, 3, 4)
)
# Brake judder: about 50 N·m of brake torque variation (Jacobsson, *Proc.
# IMechE D* 217, 2003: tens of N·m), about 150 N fore-aft at the tyre.
_BRAKE_JUDDER_FORCES = (OrderForce("wheel_1x", force_n=150.0, direction=(1.0, 0.0, 0.0)),)


def _unbalance(corner: str, grams: float, hz_scale: float = 1.0) -> OrderForce:
    """*grams* out of balance at the rim of the wheel at *corner*.

    A wheel on a tire 0.5 % smaller turns 0.5 % faster (*hz_scale* 1.005).
    """
    return OrderForce(f"wheel_1x@{corner}", hz_scale, unbalance_g=grams)


def _on_wheel(corner: str, *forces: OrderForce) -> tuple[OrderForce, ...]:
    """A tyre's or brake disc's wheel-order *forces*, on the wheel at *corner*."""
    return tuple(replace(force, order_key=f"{force.order_key}@{corner}") for force in forces)


def _car(
    name: str,
    *forces: OrderForce,
    resonance: tuple[float, float] | None = None,
    coupling: Mapping[str, float] | None = None,
    **speed_laws: object,
) -> tuple[PhaseOverride, ...]:
    """A car with the fault *forces* (and a body *resonance*), which every sensor reads.

    Each sensor plays one profile, so the forces ride on the road profile under
    the road override's gains, scaled back so each force is as named.
    *coupling* reads a target's sensors that many times as strongly: a sensor
    on a stiff spot, or a broken mount that passes more.
    """
    profile = _road_with(f"physical_{name}", forces=forces, resonance=resonance, **speed_laws)
    return (
        _on("all", profile),
        *(_on(target, profile, gain) for target, gain in (coupling or {}).items()),
    )


def _imbalance(corner: str, grams: float = _LOST_WEIGHT_G) -> tuple[PhaseOverride, ...]:
    """A car whose wheel at *corner* is *grams* out of balance."""
    return _car(f"{corner}_{grams:g}g", _unbalance(corner, grams))


def _lost_weight(corner: str) -> tuple[PhaseOverride, ...]:
    """The wheel at *corner* lost a balancing weight."""
    return _sized((_ov(corner, "wheel_imbalance", 0.85, 1.0),), _imbalance(corner))


_I4 = _car("i4_second_order", *_I4_SECOND_ORDER_FORCES)
_PROPSHAFT = _car("propshaft_imbalance", *_PROPSHAFT_IMBALANCE_FORCES)
_ENGINE_HUM = _car("engine_hum", *_ENGINE_HUM_FORCES)
_ENGINE_FIRST_ORDER_CAR = _car("engine_first_order", *_ENGINE_FIRST_ORDER_FORCES)
_FRONT_JUDDER = _car(
    "front_brake_judder",
    *_on_wheel("front-left", *_BRAKE_JUDDER_FORCES),
    *_on_wheel("front-right", *_BRAKE_JUDDER_FORCES),
)
_REAR_JUDDER = _car(
    "rear_brake_judder",
    *_on_wheel("rear-left", *_BRAKE_JUDDER_FORCES),
    *_on_wheel("rear-right", *_BRAKE_JUDDER_FORCES),
)


_ROAD_SPEED_NOISE = _road_with("road_speed_noise")
# A healthy car: every wheel keeps some residual imbalance after balancing, a
# little more at rear-right, and each sensor couples to its corner a little
# differently. A faint seat/body mode rings at 11.5 Hz. Rear-right alone at this
# level is the barely-there fault below; spread over all four it is residual.
# (With rear-right twice the others, 0.08 against 0.03-0.05, rear-right stands
# out 1.7x and the benchmark calls it a mild rear-right imbalance: where
# residual ends and a fault begins is a product decision, not set here.)
# Physically: 2-3.5 g at each rim, under the balancing tolerance.
_RESIDUAL_BODY = (11.5, 0.02)
_RESIDUAL_G = {"front-left": 2.0, "front-right": 2.5, "rear-left": 3.0, "rear-right": 3.5}
_RESIDUAL_COUPLING = {"front-left": 1.0, "front-right": 1.25, "rear-left": 0.8, "rear-right": 1.1}


def _residual_imbalance(
    body: tuple[float, float], name: str = "residual"
) -> tuple[PhaseOverride, ...]:
    """A healthy car's residual imbalance at every corner, with the body mode *body*."""
    corners = {
        corner: _road_with(f"{name}_{corner}", _Layer("wheel_mild_imbalance", gain), resonance=body)
        for corner, gain in (
            ("front-left", 0.02),
            ("front-right", 0.025),
            ("rear-left", 0.03),
            ("rear-right", 0.035),
        )
    }
    return _sized(
        (
            _on("all", _road_with(f"{name}_road", resonance=body), 0.9),
            *(_on(corner, corners[corner], _RESIDUAL_COUPLING[corner]) for corner in corners),
        ),
        _car(
            name,
            *(_unbalance(corner, grams) for corner, grams in _RESIDUAL_G.items()),
            resonance=body,
            coupling={"all": 0.9, **_RESIDUAL_COUPLING},
        ),
    )


_RESIDUAL_IMBALANCE = _residual_imbalance(_RESIDUAL_BODY)
# The same healthy car with a stronger 13 Hz body mode, which the wheel order
# passes through on the motorway: a vibration found, but no cause. The faint
# wheel order it lifts is a healthy car's residual, not a worksheet row.
_RESIDUAL_UNDER_13HZ = _residual_imbalance((13.0, 0.1), "residual_13hz")
# A faint (physically: mild) front-left imbalance under a strong 12 Hz body
# resonance every sensor feels.
_BODY_12HZ = (12.0, 0.3)
_FAINT_FL_UNDER_RESONANCE = _sized(
    (
        _on("all", _road_with("body_12hz", resonance=_BODY_12HZ)),
        _on(
            "front-left",
            _road_with(
                "faint_fl_body_12hz", _Layer("wheel_mild_imbalance", 0.15), resonance=_BODY_12HZ
            ),
        ),
    ),
    _car("mild_fl_body_12hz", _unbalance("front-left", _MILD_G), resonance=_BODY_12HZ),
)
# An imbalance (which shakes with the square of the speed) a suspension mode
# amplifies threefold between 95 and 115 km/h.
_RESONANT_BAND_KMH = (95.0, 115.0)
_FL_SPEED_SQUARED_RESONANT = _sized(
    (
        _on(
            "front-left",
            _road_with(
                "fl_speed_squared_resonant",
                _Layer("wheel_imbalance", 0.85),
                order_resonance_kmh=(*_RESONANT_BAND_KMH, 3.0),
            ),
        ),
    ),
    _car(
        "fl_speed_squared_resonant",
        _unbalance("front-left", _LOST_WEIGHT_G),
        order_resonance_kmh=(*_RESONANT_BAND_KMH, 3.0),
    ),
)
# A front-left imbalance: the other corners feel some of it through the
# subframe (front-right most), and the front-right sensor is mounted on a stiff
# spot that reads everything 2.5 times as strongly.
_FL_IMBALANCE_LAYERED = _road_with("fl_imbalance", _Layer("wheel_imbalance", 0.85))
_FL_FELT_AT_FR = _road_with("fl_felt_at_fr", _Layer("wheel_imbalance", 0.85 * 0.3))
_FL_FELT_AT_REAR = _road_with("fl_felt_at_rear", _Layer("wheel_imbalance", 0.85 * 0.12))
_FR_STIFF_MOUNT = _sized(
    (
        _on("all", _FL_FELT_AT_REAR),
        _on("front-left", _FL_IMBALANCE_LAYERED),
        _on("front-right", _FL_FELT_AT_FR, 2.5),
    ),
    _car(
        "fl_imbalance_stiff_fr",
        _unbalance("front-left", _LOST_WEIGHT_G),
        coupling={"front-right": 2.5},
    ),
)
# Both front wheels out of balance after a tire fitting (0.6 and 0.5;
# physically 25 g and 20 g), the new front-right tire 0.5 % smaller than the
# front-left, so the two tones beat. Each front sensor also feels the other
# front wheel, the rear ones both, faintly.
_FR_TIRE = 1.005
_BOTH_FRONT_TUNED = (
    _on(
        "all",
        _road_with(
            "both_front_felt_at_rear",
            _Layer("wheel_imbalance", 0.6 * 0.12),
            _Layer("wheel_imbalance", 0.5 * 0.12, _FR_TIRE),
        ),
    ),
    _on(
        "front-left",
        _road_with(
            "both_front_at_fl",
            _Layer("wheel_imbalance", 0.6),
            _Layer("wheel_imbalance", 0.5 * 0.3, _FR_TIRE),
        ),
    ),
    _on(
        "front-right",
        _road_with(
            "both_front_at_fr",
            _Layer("wheel_imbalance", 0.5, _FR_TIRE),
            _Layer("wheel_imbalance", 0.6 * 0.3),
        ),
    ),
)
_BOTH_FRONT = _sized(
    _BOTH_FRONT_TUNED,
    _car(
        "both_front",
        _unbalance("front-left", 25.0),
        _unbalance("front-right", 20.0, _FR_TIRE),
    ),
)

# -- road-excited structural modes ------------------------------------------------
# The road shakes the car's structural modes broadly: a hump about the mode, not
# a line. Every sensor feels it whatever plays there (see "Simulated road
# resonances" in docs/testing.md); the sensors sit near the suspension mounts.
# A seat/subframe mode near 15 Hz that carries most of the car's ride vibration
# (40 mg vertical at 100 km/h, the top of measured seat levels): on the motorway
# the wheel order of either car runs through it (default car 14-17 Hz, other
# car 16-19 Hz), in town the driveline and engine orders do.
_SEAT_MODE = RoadResonance(hz=15.0, q=6.0, rms_mg=(20.0, 20.0, 40.0))
# Soft tyres on a broken surface: wheel hop rings broadly about 13 Hz at 60 mg
# vertical near the suspension mounts at 100 km/h. (At 80 mg its strongest
# peaks reach the 26 dB a no-fault report calls a vibration found.)
_WHEEL_HOP = RoadResonance(hz=13.0, q=3.0, rms_mg=(30.0, 30.0, 60.0))


def _with_mode(base: str, mode: RoadResonance) -> Profile:
    """The simulator profile *base* on a road that also rings *mode*."""
    profile = replace(
        PROFILE_LIBRARY[base],
        name=f"bench_{base}_{mode.hz:g}hz_q{mode.q:g}",
        road_resonances=(*ROAD_RESONANCES, mode),
    )
    _LAYERED_PROFILES[profile.name] = profile
    return profile


def _healthy_with(mode: RoadResonance) -> PhaseOverride:
    return _ov("all", _with_mode("rough_road", mode).name, _ROAD_SCENE_GAIN, _ROAD_AMP)


def _mild_front_left_with(mode: RoadResonance) -> tuple[PhaseOverride, ...]:
    """bench-mild-front-left-wheel-sweep's imbalance, on a road that rings *mode*."""
    return _sized(
        (
            _healthy_with(mode),
            _ov("front-left", _with_mode("wheel_mild_imbalance", mode).name, 0.15, 1.0),
        ),
        _car(
            f"mild_fl_{mode.hz:g}hz_q{mode.q:g}",
            _unbalance("front-left", _MILD_G),
            road_resonances=(*ROAD_RESONANCES, mode),
        ),
    )


_HEALTHY_SEAT_MODE = _healthy_with(_SEAT_MODE)
_HEALTHY_WHEEL_HOP = _healthy_with(_WHEEL_HOP)
_MILD_FL_SEAT_MODE = _mild_front_left_with(_SEAT_MODE)
_MILD_FL_WHEEL_HOP = _mild_front_left_with(_WHEEL_HOP)

_BENCH_PROFILES = {
    profile.name: profile
    for profile in (
        _ENGINE_FIRST_ORDER,
        _SIX_FIRING,
        _THREE_FIRING,
        _V8_FIRING,
        _PROPSHAFT_JOINT,
        _BRAKE_JUDDER,
        _TIRE_OUT_OF_ROUND,
        _IMBALANCED_OVAL_TIRE,
        _with_engine_hum("rough_road", 0.28 * 0.52),
        _with_engine_hum("wheel_imbalance", 0.85),
        *_LAYERED_PROFILES.values(),
    )
}


@pytest.fixture(autouse=True)
def _bench_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, profile in bench_profiles().items():
        monkeypatch.setitem(PROFILE_LIBRARY, name, profile)


def bench_profiles() -> dict[str, Profile]:
    """The simulator profiles the benchmark's drives play, by name.

    Profiles layered further down the module register after ``_BENCH_PROFILES``
    is built. With physical fault amplitudes the simulator's own fault
    profiles play their physical sizes too.
    """
    physical = FAULT_AMPLITUDES is FaultAmplitudes.PHYSICAL
    return {**_BENCH_PROFILES, **_LAYERED_PROFILES, **(_PHYSICAL_LIBRARY if physical else {})}


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


def _brake_step(
    *, braking: tuple[PhaseOverride, ...] = (), from_kmh: float = 70.0
) -> tuple[ScenarioPhase, ...]:
    """The guided brake step: to 80 km/h, then three firm stops to 20.

    Each stop sheds 60 km/h in 6 s (0.28 g), a firm stop short of an emergency
    one; *braking* faults play only then.
    """
    phases = [_phase("brake-speed-up", 6.0, from_kmh, 80.0, guided="brake")]
    for stop in range(3):
        phases.append(_phase(f"brake-{stop}", 6.0, 80.0, 20.0, *braking, guided="brake"))
        phases.append(_phase(f"brake-speed-up-{stop}", 6.0, 20.0, 80.0, guided="brake"))
    return tuple(phases)


def _sweep(*faults: PhaseOverride) -> tuple[ScenarioPhase, ...]:
    """Sweep 50->115 km/h, hold 90, then a short coast to 70."""
    return (
        _phase("sweep", 12.0, 50.0, 115.0, *faults),
        _phase("hold", 6.0, 90.0, 90.0, *faults),
        _phase("coast", 4.0, 90.0, 70.0, *faults),
    )


def _winding_road(*faults: PhaseOverride) -> tuple[ScenarioPhase, ...]:
    """A country road at 60-85 km/h, bend after bend (radius 100-250 m, up to 0.3 g sideways)."""
    return (
        _phase("straight", 4.0, 70.0, 85.0, *faults),
        _phase("left-bend", 6.0, 85.0, 85.0, *faults, turn_radius_m=200.0),
        _phase("right-bend", 6.0, 85.0, 75.0, *faults, turn_radius_m=-150.0),
        _phase("tight-left", 5.0, 75.0, 60.0, *faults, turn_radius_m=100.0),
        _phase("right-exit", 5.0, 60.0, 80.0, *faults, turn_radius_m=-250.0),
    )


def _hard_pulls(*faults: PhaseOverride) -> tuple[ScenarioPhase, ...]:
    """Two hard pulls (about 0.3 g, 40->125 and 90->130 km/h) with a lift-off between."""
    return (
        _phase("pull", 8.0, 40.0, 125.0, *faults),
        _phase("lift", 8.0, 125.0, 90.0, *faults),
        _phase("pull-again", 4.0, 90.0, 130.0, *faults),
    )


def _motorway_stops(
    *,
    braking: tuple[PhaseOverride, ...] = (),
    always: tuple[PhaseOverride, ...] = (),
    coast: bool = False,
) -> tuple[ScenarioPhase, ...]:
    """Three motorway stops: cruise at 120 km/h, brake firmly to 40 and speed up again.

    Braking 120->40 km/h in 6 s sheds 3.7 m/s^2 (0.38 g); *braking* faults play
    only then. With *coast* the driver lifts off instead and the car rolls from
    120 to 90 km/h in 10 s (0.08 g), the way a car coasts without the brakes.
    """
    phases: list[ScenarioPhase] = []
    for stop in range(3):
        phases.append(_phase(f"cruise-{stop}", 10.0, 120.0, 120.0, *always))
        if coast:
            phases.append(_phase(f"coast-{stop}", 10.0, 120.0, 90.0, *always))
            phases.append(_phase(f"speed-up-{stop}", 8.0, 90.0, 120.0, *always))
        else:
            phases.append(_phase(f"brake-{stop}", 6.0, 120.0, 40.0, *always, *braking))
            phases.append(_phase(f"speed-up-{stop}", 12.0, 40.0, 120.0, *always))
    return tuple(phases)


def _ev_stops(*judder: PhaseOverride) -> tuple[ScenarioPhase, ...]:
    """Four motorway stops in an EV: two firm stops on the discs, two on regeneration.

    The firm stops (120->40 km/h in 6 s, 0.38 g) use the friction brakes, where
    *judder* plays. The other two shed 0.25 g (120->67 km/h in 6 s), which
    regenerative braking alone delivers without touching the discs.
    """
    phases: list[ScenarioPhase] = []
    for stop in range(4):
        friction = stop % 2 == 0
        low = 40.0 if friction else 67.0
        phases.append(_phase(f"cruise-{stop}", 10.0, 120.0, 120.0))
        phases.append(_phase(f"brake-{stop}", 6.0, 120.0, low, *(judder if friction else ())))
        phases.append(_phase(f"speed-up-{stop}", 12.0, low, 120.0))
    return tuple(phases)


# Held at 75-76 km/h, and the tone is there for 12 s of the 28 s drive.
_FAINT_ENGINE_REASONS = frozenset({"narrow_speed_range", "intermittent"})

_ENGINE_AT_ENGINE_BAY = _sized(
    (
        _ov("front-axle", "engine_order", 0.74, 0.94),
        _ov("VS-70 engine", "engine_order", 0.74, 0.94),
    ),
    _I4,
)
# A hatchback's 5-speed gearbox: 3rd, 4th and 5th (its top gear, the car's own).
_THIRD, _FOURTH, _FIFTH = 1.29, 0.97, 0.80


def _upshifts(*faults: PhaseOverride) -> tuple[ScenarioPhase, ...]:
    """Pull from 30 to 100 km/h, shifting up from 3rd through 4th to 5th."""
    return (
        _phase("third", 8.0, 30.0, 55.0, *faults, gear=_THIRD),
        _phase("fourth", 8.0, 55.0, 80.0, *faults, gear=_FOURTH),
        _phase("fifth", 8.0, 80.0, 100.0, *faults, gear=_FIFTH),
    )


GEAR_CASES = (
    # GPS only, in a direct (1:1) gear: the engine turns as fast as the propshaft,
    # so its orders sit on the driveline's.
    Case(
        "bench-engine-direct-gear-sweep",
        (
            _phase("sweep", 14.0, 40.0, 90.0, *_ENGINE_AT_ENGINE_BAY, gear=1.0),
            _phase("hold", 6.0, 90.0, 90.0, *_ENGINE_AT_ENGINE_BAY, gear=1.0),
        ),
        # The data cannot tell them apart: a hedged driveline guess, never Strong.
        Expected(
            verdicts=frozenset({"fault", "weak_evidence"}),
            source="driveline",
            zones=frozenset({"front_axle", *DRIVELINE_ZONES}),
            order_codes=frozenset({"P1", "P2"}),
            levels=frozenset({"moderate", "weak"}),
        ),
        layout=WITH_ENGINE_BAY,
        cars=("default",),
    ),
    Case(
        "bench-guided-engine-direct-gear",
        (
            _phase("sweep", 8.0, 40.0, 90.0, *_ENGINE_AT_ENGINE_BAY, guided="sweep", gear=1.0),
            _phase("hold", 6.0, 90.0, 90.0, *_ENGINE_AT_ENGINE_BAY, guided="hold", gear=1.0),
            _phase(
                "coast",
                10.0,
                90.0,
                60.0,
                _ov("all", "engine_idle", 0.2, 0.6),
                guided="coast_down",
            ),
        ),
        # It stops in neutral: the engine, in the gear that puts E2 on P2.
        _fault("engine", {"engine_bay"}, "E2", speed_dependence="engine_speed", levels=MODERATE),
        layout=WITH_ENGINE_BAY,
        cars=("default",),
    ),
    # OBD with measured RPM while shifting up: the engine order follows the RPM
    # through every shift, which no wheel or driveline order does.
    Case(
        "bench-obd-rpm-upshift-engine",
        _upshifts(
            *_sized(
                (
                    _ov("VS-70 engine", "engine_order", 0.74, 0.94),
                    _ov("front-axle", "engine_order", 0.42, 0.94),
                ),
                _I4,
            )
        ),
        _fault("engine", {"engine_bay"}, "E2"),
        layout=WITH_ENGINE_BAY,
        speed_source="obd2",
        obd_rpm=True,
        cars=("other",),
    ),
    Case(
        "bench-obd-rpm-upshift-front-left-wheel",
        _upshifts(*_lost_weight("front-left")),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True),
        speed_source="obd2",
        obd_rpm=True,
        cars=("other",),
    ),
    # Bend after bend the outer wheels run up to 0.7 % faster than the inner
    # ones, and the faulty wheel's order moves with every bend: still that wheel.
    Case(
        "bench-winding-road-front-right-wheel",
        _winding_road(*_lost_weight("front-right")),
        _fault("wheel/tire", {"front_right_wheel"}, "T1", dominant_corner=True),
    ),
    # Pulling hard the driven wheels slip about 3.5 % ahead of the road speed,
    # the others not at all: a driven wheel's order runs that far off the line
    # the speed sets while pulling, and back on it when the driver lifts off.
    Case(
        "bench-hard-pulls-driven-rear-left-wheel",
        _hard_pulls(*_lost_weight("rear-left")),
        _fault("wheel/tire", {"rear_left_wheel"}, "T1", dominant_corner=True),
        cars=("rwd",),
    ),
    Case(
        "bench-hard-pulls-driven-front-right-wheel",
        _hard_pulls(*_lost_weight("front-right")),
        _fault("wheel/tire", {"front_right_wheel"}, "T1", dominant_corner=True),
        cars=("fwd",),
    ),
    # The OBD speed reads 4 % over the true speed (a speedometer may read high,
    # never low, under UN R39): every wheel order sits 4 % under where the
    # reported speed places it, still that wheel.
    Case(
        "bench-obd-speed-over-read-front-left-wheel-sweep",
        _sweep(*_lost_weight("front-left")),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True),
        speed_source="obd2",
        obd_speed_over_read=0.04,
    ),
)


def _eight_speed_upshifts(*faults: PhaseOverride) -> tuple[ScenarioPhase, ...]:
    """Pull from 30 to 115 km/h, shifting up from 5th through 6th and 7th to 8th."""
    return (
        _phase("fifth", 8.0, 30.0, 55.0, *faults, gear=_FIFTH_OF_8),
        _phase("sixth", 8.0, 55.0, 75.0, *faults, gear=_SIXTH_OF_8),
        _phase("seventh", 8.0, 75.0, 95.0, *faults, gear=_SEVENTH_OF_8),
        _phase("eighth", 8.0, 95.0, 115.0, *faults, gear=_EIGHTH_OF_8),
    )


_SIX_AT_ENGINE_BAY = _sized(
    (
        _ov("front-axle", _SIX_FIRING.name, 0.74, 0.94),
        _ov("VS-70 engine", _SIX_FIRING.name, 0.74, 0.94),
    ),
    _car("six_firing", *_SIX_FIRING_FORCES),
)
_PROPSHAFT_JOINT_AT_REAR = _sized(
    (
        _ov("rear-axle", _PROPSHAFT_JOINT.name, 0.80, 0.95),
        _ov("front-axle", _PROPSHAFT_JOINT.name, 0.35, 0.60),
    ),
    _car("propshaft_joint", *_PROPSHAFT_JOINT_FORCES),
)
ENGINE_PROFILE_CASES = (
    # The six shaking at its firing rhythm in top gear, GPS only: E3 and
    # the propshaft's P2 are the same peaks, so the report names both and is
    # never Strong. Felt strongest at the front, the engine is named first.
    Case(
        "bench-inline6-firing-top-gear-sweep",
        _sweep(*_SIX_AT_ENGINE_BAY),
        _fault("engine", {"engine_bay"}, "E3", levels=MODERATE),
        layout=WITH_ENGINE_BAY,
        cars=("inline_6",),
    ),
    # A real propshaft joint fault on the same car, GPS only: the same two names,
    # the propshaft first, felt strongest at the rear axle.
    Case(
        "bench-inline6-propshaft-joint-sweep",
        _sweep(*_PROPSHAFT_JOINT_AT_REAR),
        _fault("driveline", DRIVELINE_ZONES, "P2", levels=MODERATE),
        cars=("inline_6",),
    ),
    # The guided coast-down: the shake stops when the engine drops to idle in
    # neutral, so it is the engine's firing rhythm.
    Case(
        "bench-inline6-guided-firing",
        _guided(*_SIX_AT_ENGINE_BAY, coast=(_ov("all", "engine_idle", 0.2, 0.6),)),
        _fault(
            "engine",
            {"engine_bay"},
            "E3",
            speed_dependence="engine_speed",
            levels=MODERATE_OR_STRONG,
        ),
        layout=WITH_ENGINE_BAY,
        cars=("inline_6",),
    ),
    # OBD-II RPM while shifting up through 5th to 8th: E3 follows the RPM through
    # every shift and sits on P2 only in 8th.
    Case(
        "bench-inline6-obd-rpm-firing-upshifts",
        _eight_speed_upshifts(*_SIX_AT_ENGINE_BAY),
        _fault("engine", {"engine_bay"}, "E3"),
        layout=WITH_ENGINE_BAY,
        speed_source="obd2",
        obd_rpm=True,
        cars=("inline_6",),
    ),
    # The propshaft joint on the same pull: P2 follows the speed, not the RPM.
    Case(
        "bench-inline6-obd-rpm-propshaft-joint-upshifts",
        _eight_speed_upshifts(*_PROPSHAFT_JOINT_AT_REAR),
        _fault("driveline", DRIVELINE_ZONES, "P2", levels=MODERATE_OR_STRONG),
        speed_source="obd2",
        obd_rpm=True,
        cars=("inline_6",),
    ),
    Case("bench-inline6-healthy-sweep", _sweep(), NO_FAULT, cars=("inline_6",)),
    # Each engine's firing rhythm where no road order sits: the engine, Strong.
    Case(
        "bench-inline-3-firing-sweep",
        _sweep(
            *_sized(
                (
                    _ov("front-axle", _THREE_FIRING.name, 0.74, 0.94),
                    _ov("rear-axle", _THREE_FIRING.name, 0.42, 0.94),
                ),
                _car("three_firing", *_THREE_FIRING_FORCES),
            )
        ),
        _fault("engine", {"engine_bay"}, "E1.5"),
        cars=("inline_3",),
    ),
    Case(
        "bench-inline-4-firing-sweep",
        _sweep(
            *_sized(
                (
                    _ov("front-axle", "engine_order", 0.74, 0.94),
                    _ov("rear-axle", "engine_order", 0.42, 0.94),
                ),
                _I4,
            )
        ),
        _fault("engine", {"engine_bay"}, "E2"),
        cars=("inline_4",),
    ),
    Case(
        "bench-v8-firing-sweep",
        _sweep(
            *_sized(
                (
                    _ov("front-axle", _V8_FIRING.name, 0.74, 0.94),
                    _ov("rear-axle", _V8_FIRING.name, 0.42, 0.94),
                ),
                _car("v8_firing", *_V8_FIRING_FORCES),
            )
        ),
        _fault("engine", {"engine_bay"}, "E4"),
        cars=("v8",),
    ),
)

EV_CASES = (
    Case(
        "bench-ev-front-left-wheel-sweep",
        _sweep(*_lost_weight("front-left")),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True),
        cars=("ev", "ev_no_ratio"),
    ),
    # A rear drive unit whose motor is out of balance: once per motor revolution.
    Case(
        "bench-ev-rear-motor-sweep",
        _sweep(
            *_sized(
                (
                    _ov("rear-axle", "driveshaft_imbalance", 0.80, 0.95),
                    _ov("front-axle", "driveshaft_imbalance", 0.35, 0.60),
                ),
                _PROPSHAFT,
            )
        ),
        _fault("driveline", DRIVELINE_ZONES, "P1"),
        # Without the motor's ratio no order explains the shake: the report has
        # no cause to name, but it must not call the run vibration-free.
        by_car={
            "ev_no_ratio": Expected(
                verdicts=frozenset({"no_fault", "weak_evidence"}),
                levels=WEAK_ONLY,
                unexplained_vibration=True,
            )
        },
        cars=("ev", "ev_no_ratio"),
    ),
)


def _long_sweep(*faults: PhaseOverride) -> tuple[ScenarioPhase, ...]:
    """Sweep 50->120 km/h, hold 100, then a short coast to 80."""
    return (
        _phase("sweep", 14.0, 50.0, 120.0, *faults),
        _phase("hold", 6.0, 100.0, 100.0, *faults),
        _phase("coast", 4.0, 100.0, 80.0, *faults),
    )


def _city(*faults: PhaseOverride) -> tuple[ScenarioPhase, ...]:
    """Stop-and-go in town, never above 50 km/h: two firm stops and a crawl."""
    return (
        _phase("idle", 4.0, 0.0, 0.0, *faults),
        _phase("pull-away", 8.0, 0.0, 45.0, *faults),
        _phase("street", 6.0, 45.0, 45.0, *faults),
        _phase("stop", 4.5, 45.0, 0.0, *faults),
        _phase("lights", 3.0, 0.0, 0.0, *faults),
        _phase("pull-away-2", 6.0, 0.0, 35.0, *faults),
        _phase("traffic", 5.0, 35.0, 35.0, *faults),
        _phase("crawl", 4.0, 35.0, 20.0, *faults),
        _phase("speed-up", 7.0, 20.0, 48.0, *faults),
        _phase("avenue", 6.0, 48.0, 48.0, *faults),
        _phase("stop-2", 4.0, 48.0, 10.0, *faults),
    )


def _motorway(*faults: PhaseOverride) -> tuple[ScenarioPhase, ...]:
    """A long motorway cruise between 110 and 130 km/h."""
    return (
        _phase("cruise", 10.0, 120.0, 120.0, *faults),
        _phase("overtake", 6.0, 120.0, 130.0, *faults),
        _phase("fast-lane", 8.0, 130.0, 130.0, *faults),
        _phase("lift-off", 12.0, 130.0, 110.0, *faults),
        _phase("roadworks", 10.0, 110.0, 110.0, *faults),
        _phase("merge", 6.0, 110.0, 125.0, *faults),
        _phase("cruise-2", 6.0, 125.0, 125.0, *faults),
    )


def _under_load(*load: PhaseOverride) -> tuple[ScenarioPhase, ...]:
    """Two pulls between steady and coasting stretches; *load* plays only while pulling."""
    return (
        _phase("steady", 6.0, 60.0, 60.0),
        _phase("pull", 8.0, 60.0, 100.0, *load),
        _phase("steady-2", 6.0, 100.0, 100.0),
        _phase("lift-off", 8.0, 100.0, 70.0),
        _phase("pull-2", 8.0, 70.0, 110.0, *load),
        _phase("steady-3", 5.0, 110.0, 110.0),
    )


# A healthy car is no fault, at most a hedged guess spread over the car: never
# one corner to fix.
HEALTHY_OR_SPREAD = Expected(
    verdicts=frozenset({"no_fault", "weak_evidence"}),
    levels=WEAK_ONLY,
    weak_reasons=frozenset({"spread_across_locations"}),
)
_FL_IMBALANCE = _lost_weight("front-left")
# A rear-right wheel that lost a weight; the rear-left keeps a little imbalance.
_RR_LOST_WEIGHT_PHYSICAL = _car(
    "rr_lost_weight", _unbalance("rear-right", _LOST_WEIGHT_G), _unbalance("rear-left", 2.5)
)
_FL_FAULT = _fault("wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True)
_DRIVELINE_UNDER_LOAD = _sized(
    (
        _ov("rear-axle", "driveshaft_imbalance", 0.80, 0.95),
        _ov("front-axle", "driveshaft_imbalance", 0.35, 0.60),
    ),
    _PROPSHAFT,
)

REALISM_CASES = (
    # The main false-positive risk: a healthy car with residual imbalance on
    # every wheel, uneven sensor coupling, road noise growing with speed and a
    # faint body mode.
    Case(
        "bench-healthy-residual-imbalance-sweep",
        _long_sweep(*_RESIDUAL_IMBALANCE),
        HEALTHY_OR_SPREAD,
    ),
    # A mild imbalance (bench-mild-front-left-wheel-sweep's level, Strong on its
    # own) the order sweeps through a strong body resonance: still that wheel,
    # and the resonance is no fault of its own.
    Case(
        "bench-faint-front-left-under-body-resonance-sweep",
        _long_sweep(*_FAINT_FL_UNDER_RESONANCE),
        Expected(
            verdicts=frozenset({"fault", "weak_evidence"}),
            source="wheel/tire",
            zones=frozenset({"front_left_wheel"}),
            order_codes=frozenset({"T1"}),
            levels=frozenset({"strong", "moderate", "weak"}),
        ),
        idealised_floor=IdealisedFloor.MISSED_UNDER_WHEEL_HOP,
    ),
    # An imbalance growing with the square of the speed and amplified in a band:
    # the report names the speeds where it shakes hardest.
    Case(
        "bench-front-left-resonant-speed-band-sweep",
        (
            _phase("sweep", 16.0, 50.0, 130.0, *_FL_SPEED_SQUARED_RESONANT),
            _phase("hold", 4.0, 130.0, 130.0, *_FL_SPEED_SQUARED_RESONANT),
            _phase("coast", 12.0, 130.0, 70.0, *_FL_SPEED_SQUARED_RESONANT),
        ),
        replace(_FL_FAULT, peak_speed_kmh=_RESONANT_BAND_KMH),
    ),
    # A GPS receiver reports once a second and about 0.8 s late: while pulling
    # from 30 to 100 km/h the speed it gives lags the wheels by 2-3 km/h.
    Case(
        "bench-gps-lag-upshift-front-left-wheel",
        _upshifts(*_FL_IMBALANCE),
        _FL_FAULT,
        speed_lag_s=0.8,
        speed_report_period_s=1.0,
    ),
    # A propshaft or CV joint that shakes only under load: the driveline, while
    # accelerating, never a wheel.
    Case(
        "bench-driveline-under-load",
        _under_load(*_DRIVELINE_UNDER_LOAD),
        Expected(
            verdicts=frozenset({"fault", "weak_evidence"}),
            source="driveline",
            zones=frozenset(DRIVELINE_ZONES),
            order_codes=frozenset({"P1"}),
            levels=frozenset({"moderate", "weak"}),
            dominant_phase="acceleration",
        ),
    ),
    # The front-right sensor reads 2.5 times as strongly as the others: the
    # imbalance it feels from front-left must not move the fault to its corner.
    Case(
        "bench-front-left-wheel-stiff-front-right-mount-sweep",
        _sweep(*_FR_STIFF_MOUNT),
        Expected(
            verdicts=frozenset({"fault", "weak_evidence"}),
            source="wheel/tire",
            zones=frozenset({"front_left_wheel", "front_axle"}),
            order_codes=frozenset({"T1"}),
            levels=frozenset({"strong", "moderate", "weak"}),
        ),
    ),
    # Both front wheels out of balance: the front axle, not one corner nor all four.
    Case(
        "bench-both-front-wheels-sweep",
        _sweep(*_BOTH_FRONT),
        _fault("wheel/tire", {"front_axle"}, "T1", levels=MODERATE_OR_STRONG),
        idealised_floor=IdealisedFloor.HUMP_SCATTER,
    ),
    # The main cases on other drives: stop-and-go in town and a motorway cruise.
    Case(
        "bench-healthy-city",
        _city(),
        NO_FAULT,
        idealised_floor=IdealisedFloor.HUMP_MATCHES_IN_TOWN,
    ),
    Case(
        "bench-healthy-residual-imbalance-city",
        _city(*_RESIDUAL_IMBALANCE),
        HEALTHY_OR_SPREAD,
        idealised_floor=IdealisedFloor.HUMP_MATCHES_IN_TOWN,
    ),
    Case(
        "bench-front-left-wheel-city",
        _city(*_FL_IMBALANCE),
        _FL_FAULT,
        idealised_floor=IdealisedFloor.HUMP_MATCHES_IN_TOWN,
    ),
    Case("bench-healthy-motorway", _motorway(), NO_FAULT),
    Case(
        "bench-healthy-residual-imbalance-motorway",
        _motorway(*_RESIDUAL_IMBALANCE),
        HEALTHY_OR_SPREAD,
    ),
    # A healthy car with a body mode the wheel order passes on the motorway: a
    # vibration no cause explains, and no faint residual listed as a cause. (On
    # the default car its wheel order sits on the mode at motorway speed.)
    Case(
        "bench-healthy-residual-under-body-resonance-motorway",
        _motorway(*_RESIDUAL_UNDER_13HZ),
        Expected(verdicts=frozenset({"no_fault"}), levels=frozenset(), unexplained_vibration=True),
        cars=("other",),
        idealised_floor=IdealisedFloor.UNEXPLAINED_BAR,
    ),
    Case("bench-front-left-wheel-motorway", _motorway(*_FL_IMBALANCE), _FL_FAULT),
    # A wheel a little out of balance (10 g): felt only at motorway speed, where
    # its force has grown with the square of the speed; still that one wheel.
    Case(
        "bench-weak-front-left-wheel-motorway",
        _motorway(*_imbalance("front-left", _WEAK_G)),
        _FL_FAULT,
        physical_only="sized in grams: tuned levels have no gram scale, and the mild and "
        "barely-there cases already gate the tuned levels a 10 g wheel would sit between",
    ),
    # A healthy car whose road-excited seat mode or wheel hop sits where the
    # orders run: every window has a peak somewhere in the order's tolerance,
    # scattered over it, not a line on the prediction. Not a fault.
    Case("bench-healthy-seat-mode-long-sweep", _long_sweep(_HEALTHY_SEAT_MODE), NO_FAULT),
    Case("bench-healthy-seat-mode-motorway", _motorway(_HEALTHY_SEAT_MODE), NO_FAULT),
    Case(
        "bench-healthy-seat-mode-city",
        _city(_HEALTHY_SEAT_MODE),
        NO_FAULT,
        idealised_floor=IdealisedFloor.HUMP_MATCHES_IN_TOWN,
    ),
    Case("bench-healthy-wheel-hop-sweep", _sweep(_HEALTHY_WHEEL_HOP), NO_FAULT),
    Case(
        "bench-healthy-wheel-hop-motorway-stops",
        _motorway_stops(always=(_HEALTHY_WHEEL_HOP,)),
        NO_FAULT,
    ),
    # The same roads with a mild front-left imbalance: its line stands on the
    # hump, still that wheel and not hedged.
    Case(
        "bench-mild-front-left-under-seat-mode-motorway",
        _motorway(*_MILD_FL_SEAT_MODE),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", levels=MODERATE_OR_STRONG),
        idealised_floor=IdealisedFloor.MISSED_UNDER_WHEEL_HOP,
    ),
    Case(
        "bench-mild-front-left-under-seat-mode-city",
        _city(*_MILD_FL_SEAT_MODE),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", levels=MODERATE_OR_STRONG),
        idealised_floor=IdealisedFloor.HUMP_MATCHES_IN_TOWN,
    ),
    Case(
        "bench-mild-front-left-under-wheel-hop-motorway",
        _motorway(*_MILD_FL_WHEEL_HOP),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", levels=MODERATE_OR_STRONG),
        idealised_floor=IdealisedFloor.MISSED_UNDER_WHEEL_HOP,
    ),
)

# -- first-drive confounders ------------------------------------------------------
# Things on a real first drive that can fool the diagnosis or hide a fault
# (``simulator/confounders.py``; "Confounders" in docs/simulator_realism.md).


def _flat_spot(scale: float, phase_rad: float) -> FlatSpot:
    """An overnight flat spot: about 60 N of radial force variation over a 40 kg
    wheel corner (US 7,377,155 B2 measures ~30 lbf), mostly vertical."""
    return FlatSpot(t1_mg=(25.0 * scale, 15.0 * scale, 80.0 * scale), phase_rad=phase_rad)


# All four tyres stood overnight, each a little differently (load, tyre age).
_FOUR_FLAT_SPOTS = {
    "front_left_wheel": _flat_spot(1.0, 0.3),
    "front_right_wheel": _flat_spot(0.7, 1.9),
    "rear_left_wheel": _flat_spot(1.3, 4.0),
    "rear_right_wheel": _flat_spot(0.85, 5.1),
}
# One tyre far worse than the others (a nylon-capped performance tyre among
# all-season ones, or one left soft overnight).
_ONE_BAD_FLAT_SPOT = {
    "front_left_wheel": _flat_spot(2.5, 0.3),
    "front_right_wheel": _flat_spot(0.5, 1.9),
    "rear_left_wheel": _flat_spot(0.6, 4.0),
    "rear_right_wheel": _flat_spot(0.5, 5.1),
}
# Four flat-spotted tyres: a vibration at the wheel orders that the drive cannot
# pin on one tyre. At most Moderate (never "go fix one wheel"), and no engine
# or driveline cause.
_WHEEL_ORDERS_AT_MOST_MODERATE = Expected(
    verdicts=frozenset({"no_fault", "weak_evidence", "fault"}),
    source="wheel/tire",
    zones=frozenset(WHEEL_ZONES | _SPREAD_WHEEL_ZONES),
    order_codes=frozenset({"T1", "T2"}),
    levels=frozenset({"moderate", "weak"}),
)
# A sensor held by loosened cable ties: the housing rings on them at 35 Hz and
# lifts off past 0.1 g (Rao ch. 3.6; Trapp & Chen 2012).
_LOOSE_FIXING = SensorFixing(resonance_hz=35.0, damping_ratio=0.06, rattle_g=0.1)
# The adhesive pad under a sensor lets go at one corner on a broken stretch
# (20 s into the drive): the 40 mm housing tips onto its 10 mm edge,
# atan(10 / 40) = 14 deg.
_PAD_LETS_GO = MountSlip(steps=((SENSORS_RUN_BEFORE_DRIVE_S + 20.0, 14.0),))
# A sensor that turned less than this on its fixing reads no more turn than a
# firm one does as the body rolls and pitches and the sensor warms (docs/metrics.md).
_UNNOTICED_TURN_DEG = 2.0


def _broken_stretch(*faults: PhaseOverride) -> tuple[ScenarioPhase, ...]:
    """A motorway cruise with a broken stretch in the middle (potholes, 15-25 s in)."""
    hits = ((0.8, "front-left"), (2.1, "right-side"), (3.0, "rear-axle"), (4.6, "front-axle"))
    return (
        _phase("cruise", 15.0, 110.0, 110.0, *faults),
        replace(
            _phase("broken", 10.0, 110.0, 100.0, *faults),
            pulses=tuple(
                PhasePulse(at_s=at_s + offset, target=target, strength=20.0)
                for offset in (0, 5)
                for at_s, target in hits
            ),
        ),
        _phase("cruise-again", 15.0, 100.0, 115.0, *faults),
    )


def _hills(*faults: PhaseOverride) -> tuple[ScenarioPhase, ...]:
    """Over a hill and down the other side: 8 % up, braking down an 8 % descent, then level.

    8 % is about the steepest grade a main road is built with (AASHTO Green Book).
    """
    return (
        _phase("level", 6.0, 70.0, 80.0, *faults),
        _phase("climb", 10.0, 80.0, 75.0, *faults, grade_pct=8.0),
        _phase("crest", 4.0, 75.0, 75.0, *faults),
        _phase("descent", 8.0, 75.0, 85.0, *faults, grade_pct=-8.0),
        _phase("brake-downhill", 5.0, 85.0, 50.0, *faults, grade_pct=-8.0),
        _phase("valley", 8.0, 50.0, 80.0, *faults),
    )


# A sensor on a springy bracket that does not rattle: its 60 Hz ring is where
# the propshaft order runs at motorway speed.
_SPRINGY_BRACKET = SensorFixing(resonance_hz=60.0, damping_ratio=0.05)


def _potholes(*faults: PhaseOverride) -> tuple[ScenarioPhase, ...]:
    """_long_sweep on a broken road: a pothole or expansion joint at a wheel every second or two."""
    hits = ((0.8, "front-left"), (2.1, "right-side"), (3.0, "rear-axle"), (4.6, "front-axle"))
    return tuple(
        replace(
            phase,
            pulses=tuple(
                PhasePulse(at_s=at_s + offset, target=target, strength=20.0)
                for offset in range(0, int(phase.duration_s) - 4, 5)
                for at_s, target in hits
            ),
        )
        for phase in _long_sweep(*faults)
    )


# Worn accessories, about five times their ISO 21940-11 balance grade, felt at
# each mounting point as their source's mass and distance give it.
def _blower(mg: float) -> AccessoryTone:
    """The HVAC blower at a mid setting (2700 rpm), leaves in its wheel."""
    return AccessoryTone(level_mg=(0.6 * mg, 0.5 * mg, mg), hz=45.0)


def _alternator(mg: float) -> AccessoryTone:
    """The alternator, belt-driven at 2.8 times the crank (2.2-3 x, Bosch Automotive Handbook)."""
    return AccessoryTone(level_mg=(mg, 0.6 * mg, 0.8 * mg), engine_order=2.8, phase_rad=1.0)


_ACCESSORIES = {
    "driver_seat": (_blower(10.0), _alternator(1.0)),
    "front_passenger_seat": (_blower(10.0), _alternator(1.0)),
    "rear_center_seat": (_blower(5.0), _alternator(0.8)),
    "trunk": (_blower(2.0), _alternator(0.5)),
    "engine_bay": (_alternator(8.0), _blower(2.0)),
    "transmission": (_alternator(4.0),),
    "front_subframe": (_alternator(4.0),),
    "driveshaft_tunnel": (_alternator(2.0),),
    "front_left_wheel": (_blower(1.5), _alternator(1.5)),
    "front_right_wheel": (_blower(1.5), _alternator(1.5)),
    "rear_left_wheel": (_alternator(0.5),),
    "rear_right_wheel": (_alternator(0.5),),
}


# A tyre with radial force variation (non-uniform stiffness or runout): a force
# fixed by its shape, so the same at every speed, at the first four wheel
# orders falling off about as 1/n (Gent & Walter, *The Pneumatic Tire*, NHTSA
# 2006, ch. 9). Its first order is as strong as the front-left imbalance's.
_IMBALANCE_T1 = PROFILE_LIBRARY["wheel_imbalance"].order_tones[0][2]
_NON_UNIFORM_TYRE = Profile(
    name="bench_non_uniform_tyre",
    tones=(),
    order_tones=tuple(
        ("wheel_1x", float(n), tuple(a / n for a in _IMBALANCE_T1)) for n in (1, 2, 3, 4)
    ),
    noise_std=24.0,
    bump_probability=0.004,
    bump_decay=0.94,
    bump_strength=(30.0, 24.0, 45.0),
    modulation_hz=0.22,
    modulation_depth=0.12,
    reference_speed_kmh=DEFAULT_SPEED_KMH,
)
_LAYERED_PROFILES[_NON_UNIFORM_TYRE.name] = _NON_UNIFORM_TYRE

# Two real faults at once, each sensor hearing both as its distance gives them.
_FL_GAIN = 0.85
_SHAFT_REAR, _SHAFT_FRONT = 0.80 * 0.95, 0.35 * 0.60
_FL_AND_PROPSHAFT_TUNED = (
    _on(
        "rear-axle",
        _road_with(
            "propshaft_with_fl_at_rear",
            _Layer("driveshaft_imbalance", _SHAFT_REAR),
            _Layer("wheel_imbalance", _FL_GAIN * 0.12),
        ),
    ),
    _on("VS-07 trunk", _road_with("propshaft_at_trunk", _Layer("driveshaft_imbalance", 0.4))),
    _on(
        "front-left",
        _road_with(
            "fl_with_propshaft",
            _Layer("wheel_imbalance", _FL_GAIN),
            _Layer("driveshaft_imbalance", _SHAFT_FRONT),
        ),
    ),
    _on(
        "front-right",
        _road_with(
            "fl_and_propshaft_at_fr",
            _Layer("wheel_imbalance", _FL_GAIN * 0.3),
            _Layer("driveshaft_imbalance", _SHAFT_FRONT),
        ),
    ),
)
_FL_AND_PROPSHAFT = _sized(
    _FL_AND_PROPSHAFT_TUNED,
    _car(
        "fl_and_propshaft", _unbalance("front-left", _LOST_WEIGHT_G), *_PROPSHAFT_IMBALANCE_FORCES
    ),
)
# Front-left and rear-right out of balance (0.85 and 0.5; physically 40 g and
# 20 g), each felt faintly across the car; the rear-right tyre 0.4 % smaller, so
# it turns a little faster.
_RR_TIRE = 1.004
_FL_AND_RR_TUNED = (
    _on(
        "all",
        _road_with(
            "fl_rr_felt_elsewhere",
            _Layer("wheel_imbalance", _FL_GAIN * 0.12),
            _Layer("wheel_imbalance", 0.5 * 0.12, _RR_TIRE),
        ),
    ),
    _on(
        "front-left",
        _road_with(
            "fl_with_rr",
            _Layer("wheel_imbalance", _FL_GAIN),
            _Layer("wheel_imbalance", 0.5 * 0.12, _RR_TIRE),
        ),
    ),
    _on(
        "rear-right",
        _road_with(
            "rr_with_fl",
            _Layer("wheel_imbalance", 0.5, _RR_TIRE),
            _Layer("wheel_imbalance", _FL_GAIN * 0.12),
        ),
    ),
)
_FL_AND_RR = _sized(
    _FL_AND_RR_TUNED,
    _car(
        "fl_and_rr",
        _unbalance("front-left", _LOST_WEIGHT_G),
        _unbalance("rear-right", 20.0, _RR_TIRE),
    ),
)
_FRONT_JUDDER_SIZED = _sized((_ov("front-axle", _BRAKE_JUDDER.name, 0.6, 1.0),), _FRONT_JUDDER)
_ENGINE_FIRST_ORDER_SIZED = _sized(
    (_ov("all", _ENGINE_FIRST_ORDER.name, 0.7, 0.9),), _ENGINE_FIRST_ORDER_CAR
)
_FAINT_INTERMITTENT_ENGINE = _sized((_ov("front-axle", "engine_order", 0.30, 0.6),), _ENGINE_HUM)
_PROPSHAFT_FAULT = _fault("driveline", DRIVELINE_ZONES, "P1", levels=MODERATE)
_ENGINE_FAULT = _fault("engine", {"engine_bay"}, "E2")


def _wobbly_cruise(kmh: float, duration_s: float, *faults: PhaseOverride) -> list[ScenarioPhase]:
    """Cruise control or a steady foot: the speed wanders +/- 2 km/h over about 10 s."""
    wander = (0.0, 1.5, 2.0, 0.5, -1.5, -2.0, -0.5, 1.0)
    points = [kmh + wander[i % len(wander)] for i in range(int(duration_s / 2.5) + 1)]
    return [
        _phase(f"cruise-{kmh:g}-{i}", 2.5, start, end, *faults)
        for i, (start, end) in enumerate(itertools.pairwise(points))
    ]


def _real_traffic(*faults: PhaseOverride) -> tuple[ScenarioPhase, ...]:
    """A suburban run: wandering cruises, a short stop, never truly steady."""
    return (
        _phase("pull-away", 8.0, 0.0, 70.0, *faults),
        *_wobbly_cruise(70.0, 12.5, *faults),
        _phase("slow", 5.0, 70.0, 20.0, *faults),
        _phase("stop", 2.0, 0.0, 0.0, *faults),
        _phase("pull-away-2", 9.0, 0.0, 95.0, *faults),
        *_wobbly_cruise(95.0, 15.0, *faults),
        _phase("lift-off", 6.0, 95.0, 80.0, *faults),
        *_wobbly_cruise(80.0, 10.0, *faults),
    )


def _town_only(*faults: PhaseOverride) -> tuple[ScenarioPhase, ...]:
    """A drive that never reaches the speeds where the fault shakes hardest (tops at 80 km/h)."""
    return (
        _phase("pull-away", 8.0, 20.0, 60.0, *faults),
        *_wobbly_cruise(60.0, 10.0, *faults),
        _phase("speed-up", 8.0, 60.0, 80.0, *faults),
        *_wobbly_cruise(80.0, 10.0, *faults),
        _phase("slow", 6.0, 80.0, 50.0, *faults),
    )


CONFOUNDER_CASES = (
    # Parking flat spots on the first kilometres: all four tyres alike, on the
    # motorway, a sweep and in town.
    Case(
        "bench-healthy-flat-spots-first-km-long-sweep",
        _long_sweep(),
        _WHEEL_ORDERS_AT_MOST_MODERATE,
        flat_spots=_FOUR_FLAT_SPOTS,
    ),
    Case(
        "bench-healthy-flat-spots-first-km-motorway",
        _motorway(),
        _WHEEL_ORDERS_AT_MOST_MODERATE,
        flat_spots=_FOUR_FLAT_SPOTS,
    ),
    # Only on the other car: on the default car, under about 38 km/h T1 is
    # below the lowest frequency analysed, so nothing tells the tyres' T3/T4
    # from its propshaft (3.08 per wheel turn) or E2 (3.94), and the town drive
    # reads as a Moderate propshaft or even a Strong engine fault. An open
    # product limit (see "not an alias of a wheel order" in docs/metrics.md).
    Case(
        "bench-healthy-flat-spots-first-km-city",
        _city(),
        _WHEEL_ORDERS_AT_MOST_MODERATE,
        cars=("other",),
        flat_spots=_FOUR_FLAT_SPOTS,
        idealised_floor=IdealisedFloor.HUMP_SCATTER,
    ),
    # One tyre far worse: it is that tyre, at its first order.
    Case(
        "bench-one-flat-spotted-tyre-first-km-long-sweep",
        _long_sweep(),
        _fault(
            "wheel/tire",
            {"front_left_wheel"},
            "T1",
            levels=frozenset({"strong", "moderate", "weak"}),
        ),
        flat_spots=_ONE_BAD_FLAT_SPOT,
        idealised_floor=IdealisedFloor.HUMP_SCATTER,
    ),
    # A loosely tied sensor rattling on a broken road: the rattle is no fault.
    # A known limit: the corners are compared as if every sensor were fixed
    # alike, and the tie's 35 Hz ring lifts that corner's residual T2 (28 Hz at
    # 100 km/h) about 2.6x, so the healthy corner can read a Moderate wheel
    # fault; never Strong, and never another source.
    Case(
        "bench-healthy-loose-front-right-mount-potholes",
        _potholes(*_RESIDUAL_IMBALANCE),
        _WHEEL_ORDERS_AT_MOST_MODERATE,
        fixings={"front_right_wheel": _LOOSE_FIXING},
    ),
    # The loose sensor next to a real fault: still the front-left wheel.
    Case(
        "bench-front-left-wheel-loose-front-right-mount-sweep",
        _sweep(*_FR_STIFF_MOUNT),
        _fault("wheel/tire", {"front_left_wheel", "front_axle"}, "T1", levels=MODERATE_OR_STRONG),
        fixings={"front_right_wheel": _LOOSE_FIXING},
        idealised_floor=IdealisedFloor.HUMP_SCATTER,
    ),
    # The faulty wheel's own sensor is the loose one: lifting off its fixing past
    # 0.1 g, it under-reads the shake and its landings raise the floor around it,
    # so the corner may read only Moderate (and faint) where a firm one reads Strong.
    Case(
        "bench-front-left-wheel-on-a-loose-mount-potholes",
        _potholes(*_FL_IMBALANCE),
        replace(_FL_FAULT, levels=MODERATE_OR_STRONG),
        fixings={"front_left_wheel": _LOOSE_FIXING},
    ),
    # The pad under a rear sensor lets go on a broken stretch: the report says
    # that sensor may be loose, and nothing else.
    Case(
        "bench-healthy-rear-left-pad-lets-go-broken-stretch",
        _broken_stretch(),
        NO_FAULT,
        slips={"rear_left_wheel": _PAD_LETS_GO},
        loose_mounts=frozenset({"rear_left_wheel"}),
    ),
    # The faulty wheel's own sensor tips on its fixing: still the front-left
    # wheel, but how strong it was there rests on a loose sensor, so never Strong.
    Case(
        "bench-front-left-wheel-pad-lets-go-broken-stretch",
        _broken_stretch(*_FL_IMBALANCE),
        replace(_FL_FAULT, levels=MODERATE),
        slips={"front_left_wheel": _PAD_LETS_GO},
        loose_mounts=frozenset({"front_left_wheel"}),
    ),
    # Grades and braking downhill turn every sensor's gravity alike: no sensor is loose.
    Case("bench-healthy-hills", _hills(), NO_FAULT),
    Case("bench-front-left-wheel-hills", _hills(*_FL_IMBALANCE), _FL_FAULT),
    # A propshaft imbalance whose order runs through a rear sensor's bracket ring.
    Case(
        "bench-driveline-springy-rear-right-bracket-sweep",
        _sweep(*_DRIVELINE_UNDER_LOAD),
        _PROPSHAFT_FAULT,
        fixings={"rear_right_wheel": _SPRINGY_BRACKET},
    ),
    # Worn accessories (blower, alternator) with a sensor everywhere: none is a fault.
    Case(
        "bench-healthy-worn-accessories-every-mount-long-sweep",
        _long_sweep(),
        NO_FAULT,
        layout=EVERY_MOUNT,
        accessories=_ACCESSORIES,
    ),
    Case(
        "bench-healthy-worn-accessories-every-mount-city",
        _city(),
        NO_FAULT,
        layout=EVERY_MOUNT,
        accessories=_ACCESSORIES,
        idealised_floor=IdealisedFloor.HUMP_MATCHES_IN_TOWN,
    ),
    Case(
        "bench-front-left-wheel-worn-accessories-every-mount-sweep",
        _sweep(*_FL_IMBALANCE),
        _FL_FAULT,
        layout=EVERY_MOUNT,
        accessories=_ACCESSORIES,
    ),
    # Two faults at once: either is the right answer, and nothing else.
    Case(
        "bench-front-left-wheel-and-propshaft-sweep",
        _sweep(*_FL_AND_PROPSHAFT),
        _FL_FAULT,
        second_fault=_PROPSHAFT_FAULT,
    ),
    # Two wheels out of balance: one finding per order names the stronger
    # corner (front-left); rear-right shows once front-left is fixed and retested.
    # The front-left carries 1.7x the rear-right's imbalance, close to the 1.5x
    # the description's "stronger at" turns at, and on the road the rear-right's
    # own level carries its share of the road's scatter: "about as strong at the
    # front-left as at the rear-right" is as true a reading.
    Case(
        "bench-front-left-and-rear-right-wheels-sweep",
        _sweep(*_FL_AND_RR),
        _fault("wheel/tire", {"front_left_wheel"}, "T1"),
    ),
    # A non-uniform tyre (radial force variation at T1-T4): the tyre, not the
    # engine or propshaft orders its harmonics land on.
    Case(
        "bench-front-left-non-uniform-tyre-long-sweep",
        _long_sweep(
            *_sized(
                (_ov("front-left", _NON_UNIFORM_TYRE.name, 0.85, 1.0),),
                _car("fl_non_uniform_tyre", *_on_wheel("front-left", *_NON_UNIFORM_TYRE_FORCES)),
            )
        ),
        _FL_FAULT,
    ),
    # Real driving: the speed is never truly steady, with a short stop.
    Case(
        "bench-front-left-wheel-real-traffic",
        _real_traffic(*_FL_IMBALANCE),
        _FL_FAULT,
        idealised_floor=IdealisedFloor.LEVEL_UNDER_THE_HUMP,
    ),
    Case(
        "bench-healthy-real-traffic",
        _real_traffic(),
        NO_FAULT,
        idealised_floor=IdealisedFloor.HUMP_MATCHES_IN_TOWN,
    ),
    # The imbalance that shakes hardest at 95-115 km/h, on a drive that never gets there.
    Case(
        "bench-front-left-resonant-band-never-reached-town",
        _town_only(*_FL_SPEED_SQUARED_RESONANT),
        replace(
            _FL_FAULT,
            verdicts=frozenset({"fault", "weak_evidence"}),
            levels=frozenset({"strong", "moderate", "weak"}),
        ),
    ),
)

BENCH_CASES = (
    Case("bench-healthy-sweep", _sweep(), NO_FAULT, cars=(*BOTH_CARS, "fwd")),
    # Staggered tires: each axle's wheels turn at their own tires' rate. A
    # healthy car's front wheels are no fault for turning faster than the
    # rear tires would, and a front wheel's imbalance is on its own axle's order.
    Case("bench-healthy-staggered-tires-sweep", _sweep(), NO_FAULT, cars=("staggered",)),
    Case(
        "bench-healthy-residual-imbalance-staggered-tires-sweep",
        _long_sweep(*_RESIDUAL_IMBALANCE),
        HEALTHY_OR_SPREAD,
        cars=("staggered",),
    ),
    Case(
        "bench-front-left-wheel-staggered-tires-sweep",
        _sweep(*_FL_IMBALANCE),
        _FL_FAULT,
        cars=("staggered",),
    ),
    # Brake judder from warped front discs: felt in the steering wheel every time
    # the car brakes from motorway speed, gone while cruising and speeding up.
    # It is the brakes, not a wheel to balance.
    Case(
        "bench-front-brake-judder-stops",
        _motorway_stops(braking=_FRONT_JUDDER_SIZED),
        _fault(
            "brakes",
            {"front_axle"},
            "T1",
            levels=MODERATE_OR_STRONG,
            dominant_phase="braking",
        ),
        idealised_floor=IdealisedFloor.MISSED_UNDER_WHEEL_HOP,
    ),
    # Rear discs judder more faintly (tuned: the rear axle brakes less; physically
    # the same disc variation as at the front): felt in the seat.
    Case(
        "bench-rear-brake-judder-stops",
        _motorway_stops(
            braking=_sized((_ov("rear-axle", _BRAKE_JUDDER.name, 0.4, 1.0),), _REAR_JUDDER)
        ),
        _fault(
            "brakes",
            {"rear_axle"},
            "T1",
            levels=MODERATE_OR_STRONG,
            dominant_phase="braking",
        ),
        idealised_floor=IdealisedFloor.MISSED_UNDER_WHEEL_HOP,
    ),
    # The full guided test drive, its brake step included: judder from warped
    # front discs only in the step's firm stops. Without the step a guided drive
    # never brakes firmly, and the brakes go unchecked.
    Case(
        "bench-guided-front-brake-judder",
        (*_guided(), *_brake_step(braking=_FRONT_JUDDER_SIZED)),
        _fault(
            "brakes",
            {"front_axle"},
            "T1",
            levels=MODERATE_OR_STRONG,
            dominant_phase="braking",
        ),
        idealised_floor=IdealisedFloor.LEVEL_UNDER_THE_HUMP,
    ),
    # A healthy car on the full guided drive: the brakes are checked, not skipped.
    Case(
        "bench-guided-healthy-brake-step",
        (*_guided(), *_brake_step()),
        NO_FAULT,
        idealised_floor=IdealisedFloor.HUMP_MATCHES_IN_TOWN,
    ),
    # An EV's judder shows only in its stops on the discs; the stops it made on
    # regeneration alone (no disc contact) do not count against it.
    Case(
        "bench-ev-brake-judder-regen-stops",
        _ev_stops(*_FRONT_JUDDER_SIZED),
        _fault(
            "brakes",
            {"front_axle"},
            "T1",
            levels=MODERATE_OR_STRONG,
            dominant_phase="braking",
        ),
        cars=("ev",),
        idealised_floor=IdealisedFloor.MISSED_UNDER_WHEEL_HOP,
    ),
    # A healthy car on the same drive, once with firm stops and once only coasting.
    # An EV's stops may have been on regeneration: its brakes are checked with a hedge.
    Case("bench-healthy-brake-stops", _motorway_stops(), NO_FAULT, cars=(*BOTH_CARS, "ev")),
    Case("bench-healthy-coast-downs", _motorway_stops(coast=True), NO_FAULT),
    # An imbalance shakes in every phase, braking included: a wheel to balance,
    # not the brakes.
    Case(
        "bench-front-left-wheel-brake-stops",
        _motorway_stops(always=_lost_weight("front-left")),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True),
    ),
    # Fixed-frequency body resonances (13/26/39 Hz) that the orders sweep through:
    # brief crossings are not an order-tracked fault.
    # At most a hedged guess, never an actionable fault.
    Case(
        "bench-fixed-resonance-sweep",
        _sweep(_ov("all", "engine_idle", 0.5, 0.8)),
        Expected(
            verdicts=frozenset({"no_fault", "weak_evidence"}),
            levels=WEAK_ONLY,
            unexplained_vibration=True,
        ),
    ),
    Case(
        "bench-rear-right-wheel-sweep",
        _sweep(
            *_sized(
                (
                    _ov("rear-right", "wheel_imbalance", 0.85, 1.0),
                    _ov("rear-left", "wheel_mild_imbalance", 0.30, 0.55),
                ),
                _RR_LOST_WEIGHT_PHYSICAL,
            )
        ),
        _fault("wheel/tire", {"rear_right_wheel"}, "T1", dominant_corner=True),
    ),
    # A mild imbalance (tuned: about 85 mg at its corner at 100 km/h; physically
    # 15 g, about 150 mg there): quiet elsewhere on the car, yet clearly the one
    # source at that corner.
    Case(
        "bench-mild-front-left-wheel-sweep",
        _sweep(
            *_sized(
                (_ov("front-left", "wheel_mild_imbalance", 0.15, 1.0),),
                _imbalance("front-left", _MILD_G),
            )
        ),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True),
        idealised_floor=IdealisedFloor.MISSED_UNDER_WHEEL_HOP,
    ),
    # Barely above the road noise (tuned: under 16 dB over the floor at its
    # corner; physically 5 g, the balancing tolerance): found and located, but
    # never "go fix it".
    Case(
        "bench-barely-there-front-left-wheel-sweep",
        _sweep(
            *_sized(
                (_ov("front-left", "wheel_mild_imbalance", 0.04, 1.0),),
                _imbalance("front-left", _BARELY_THERE_G),
            )
        ),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", levels=frozenset({"moderate", "weak"})),
        idealised_floor=IdealisedFloor.MISSED_UNDER_WHEEL_HOP,
    ),
    Case(
        "bench-rear-left-out-of-round-sweep",
        _sweep(
            *_sized(
                (_ov("rear-left", _TIRE_OUT_OF_ROUND.name, 0.85, 1.0),),
                _car("rl_out_of_round", *_on_wheel("rear-left", *_TIRE_OUT_OF_ROUND_FORCES)),
            )
        ),
        _fault("wheel/tire", {"rear_left_wheel"}, "T2", dominant_corner=True),
        # The default car's engine turns at T2 in top gear: never Strong without RPM.
        {
            "default": _fault(
                "wheel/tire", {"rear_left_wheel"}, "T2", dominant_corner=True, levels=MODERATE
            )
        },
    ),
    # Same fault, but the faulty corner's sensor loses 15 % of its frames over
    # Wi-Fi: still diagnosed, and the report says data was lost.
    Case(
        "bench-rear-right-wheel-sweep-lossy-sensor",
        _sweep(
            *_sized(
                (
                    _ov("rear-right", "wheel_imbalance", 0.85, 1.0),
                    _ov("rear-left", "wheel_mild_imbalance", 0.30, 0.55),
                ),
                _RR_LOST_WEIGHT_PHYSICAL,
            )
        ),
        _fault("wheel/tire", {"rear_right_wheel"}, "T1", dominant_corner=True),
        frame_loss={"rear_right_wheel": 0.15},
    ),
    # Lost frames keep their time in the spectrum while the car speeds up: the
    # lossy corner's line stays on the speed it was heard at, so that wheel,
    # even with almost a third of its frames gone.
    Case(
        "bench-rear-right-wheel-sweep-very-lossy-sensor",
        _sweep(
            *_sized(
                (
                    _ov("rear-right", "wheel_imbalance", 0.85, 1.0),
                    _ov("rear-left", "wheel_mild_imbalance", 0.30, 0.55),
                ),
                _RR_LOST_WEIGHT_PHYSICAL,
            )
        ),
        _fault("wheel/tire", {"rear_right_wheel"}, "T1", dominant_corner=True),
        frame_loss={"rear_right_wheel": 0.3},
        idealised_floor=IdealisedFloor.HUMP_SCATTER,
    ),
    # Every sensor loses a fifth of its frames: a mild imbalance on the wheel
    # hop is still found, and a healthy car's seat mode is still no fault.
    Case(
        "bench-mild-front-left-under-wheel-hop-sweep-lossy-sensors",
        _sweep(*_MILD_FL_WHEEL_HOP),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", levels=MODERATE_OR_STRONG),
        frame_loss={sensor.location_code: 0.2 for sensor in SENSORS},
        idealised_floor=IdealisedFloor.MISSED_UNDER_WHEEL_HOP,
    ),
    Case(
        "bench-healthy-seat-mode-long-sweep-lossy-sensors",
        _long_sweep(_HEALTHY_SEAT_MODE),
        NO_FAULT,
        frame_loss={sensor.location_code: 0.2 for sensor in SENSORS},
        idealised_floor=IdealisedFloor.HUMP_SCATTER,
    ),
    # Busy Wi-Fi: slow, one-sided clock-sync replies must not throw the sensor
    # clocks off, so the run stays (mostly) raw-backed.
    Case(
        "bench-rear-right-wheel-sweep-busy-wifi",
        _sweep(
            *_sized(
                (
                    _ov("rear-right", "wheel_imbalance", 0.85, 1.0),
                    _ov("rear-left", "wheel_mild_imbalance", 0.30, 0.55),
                ),
                _RR_LOST_WEIGHT_PHYSICAL,
            )
        ),
        _fault("wheel/tire", {"rear_right_wheel"}, "T1", dominant_corner=True),
        uplink_latency_spike_s=0.03,
    ),
    # Car start: the recording starts before the sensor clocks are synced, while
    # their bare device timers read within ~2 s of server time.
    Case(
        "bench-rear-right-wheel-sweep-car-start",
        _sweep(
            *_sized(
                (
                    _ov("rear-right", "wheel_imbalance", 0.85, 1.0),
                    _ov("rear-left", "wheel_mild_imbalance", 0.30, 0.55),
                ),
                _RR_LOST_WEIGHT_PHYSICAL,
            )
        ),
        _fault("wheel/tire", {"rear_right_wheel"}, "T1", dominant_corner=True),
        car_start=True,
    ),
    Case(
        "bench-rear-right-wheel-sweep-car-start-congested",
        _sweep(
            *_sized(
                (
                    _ov("rear-right", "wheel_imbalance", 0.85, 1.0),
                    _ov("rear-left", "wheel_mild_imbalance", 0.30, 0.55),
                ),
                _RR_LOST_WEIGHT_PHYSICAL,
            )
        ),
        _fault("wheel/tire", {"rear_right_wheel"}, "T1", dominant_corner=True),
        car_start=True,
        wifi_retry_loss=0.3,
    ),
    Case(
        "bench-rear-left-imbalanced-oval-sweep",
        _sweep(
            *_sized(
                (_ov("rear-left", _IMBALANCED_OVAL_TIRE.name, 0.85, 1.0),),
                _car("rl_imbalanced_oval", *_on_wheel("rear-left", *_IMBALANCED_OVAL_TIRE_FORCES)),
            )
        ),
        _fault("wheel/tire", {"rear_left_wheel"}, "T1", dominant_corner=True),
        idealised_floor=IdealisedFloor.HUMP_SCATTER,
    ),
    # A long neutral coast-down to 40 km/h: the imbalance fades with speed, so it
    # is seen in fewer windows than at speed, yet clearly keeps going.
    Case(
        "bench-guided-wheel-long-coastdown",
        _guided(
            *_lost_weight("front-left"),
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
    # The driver taps through the guided steps while holding 80 km/h: only the
    # hold was driven. The sweep and the coast-down are tapped but not detected,
    # and the coast-down that never shed speed does not decide what the
    # vibration follows.
    Case(
        "bench-guided-steps-tapped-at-a-steady-speed",
        (
            _phase("sweep", 8.0, 80.0, 82.0, *_FL_IMBALANCE, guided="sweep"),
            _phase("hold", 8.0, 82.0, 82.0, *_FL_IMBALANCE, guided="hold"),
            _phase("coast", 8.0, 82.0, 80.0, *_FL_IMBALANCE, guided="coast_down"),
        ),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", levels=MODERATE),
        guided_undetected=("sweep", "coast_down"),
    ),
    # In a direct (1:1) gear the engine turns as fast as the propshaft: without
    # measured RPM or a coast-down a propshaft order is never Strong.
    Case(
        "bench-driveline-sweep",
        _sweep(
            *_sized(
                (
                    _ov("rear-axle", "driveshaft_imbalance", 0.80, 0.95),
                    _ov("front-axle", "driveshaft_imbalance", 0.35, 0.60),
                ),
                _PROPSHAFT,
            )
        ),
        _fault("driveline", DRIVELINE_ZONES, "P1", levels=MODERATE),
        cars=(*BOTH_CARS, "rwd"),
    ),
    # A front-wheel-drive hatchback with the same propshaft-order tone (wheel
    # speed x final drive), strongest at the front wheels. It has no propshaft,
    # so the front axle is the place to look and the gearbox output shaft and
    # final-drive pinion, which turn at that order, what to check.
    Case(
        "bench-fwd-front-driveline-sweep",
        _sweep(
            *_sized(
                (
                    _ov("front-axle", "driveshaft_imbalance", 0.80, 0.95),
                    _ov("rear-axle", "driveshaft_imbalance", 0.35, 0.60),
                ),
                _PROPSHAFT,
            )
        ),
        _fault("driveline", {"front_axle"}, "P1", levels=MODERATE),
        cars=("fwd",),
    ),
    # An all-wheel-drive car with the same front-axle shake: both axles are driven,
    # so the front propshaft and differential come first and the propshaft to the
    # rear axle still gets checked.
    Case(
        "bench-awd-front-driveline-sweep",
        _sweep(
            *_sized(
                (
                    _ov("front-axle", "driveshaft_imbalance", 0.80, 0.95),
                    _ov("rear-axle", "driveshaft_imbalance", 0.35, 0.60),
                ),
                _PROPSHAFT,
            )
        ),
        _fault("driveline", {"front_axle", "driveshaft_tunnel"}, "P1", levels=MODERATE),
        cars=("awd",),
    ),
    Case(
        "bench-engine-sweep",
        _sweep(
            *_sized(
                (
                    _ov("front-axle", "engine_order", 0.74, 0.94),
                    _ov("rear-axle", "engine_order", 0.42, 0.94),
                ),
                _I4,
            )
        ),
        _fault("engine", {"engine_bay"}, "E2"),
    ),
    # A faint engine tone (tuned: only the front sensors hear it, just over the
    # moderate strength band there, 16-17 dB; physically an inline-4 whose
    # balance shafts leave 20 g of its second-order force, felt through the
    # car). Floor-level road noise the other sensors match near its frequency
    # must not dilute its strength into "no fault".
    # That close to the band's edge it is Moderate or Strong: the score ramps
    # across 16 dB rather than doubling at it.
    Case(
        "bench-faint-engine-front-wheels-sweep",
        _sweep(*_sized((_ov("front-axle", "engine_order", 0.027, 0.94),), _ENGINE_HUM)),
        _fault("engine", {"engine_bay"}, "E2", levels=MODERATE_OR_STRONG),
        idealised_floor=IdealisedFloor.MISSED_UNDER_WHEEL_HOP,
    ),
    # The same with a sensor on every mounting point: the engine bay, subframe
    # and gearbox sensors hear a faint tone (tuned: the nine others do not).
    Case(
        "bench-faint-engine-every-mount-sweep",
        _sweep(
            *_sized(
                (
                    _ov("VS-70 engine", "engine_order", 0.03, 0.94),
                    _ov("VS-74 subframe", "engine_order", 0.03, 0.94),
                    _ov("VS-72 gearbox", "engine_order", 0.025, 0.94),
                ),
                _ENGINE_HUM,
            )
        ),
        _fault("engine", {"engine_bay"}, "E2", levels=MODERATE_OR_STRONG),
        layout=EVERY_MOUNT,
    ),
    # Two real faults: an engine tone (tuned: the rear sensors do not hear it),
    # and a rear-left imbalance (tuned: about four times the second one in the
    # rear-right cases; physically 10 g). Either is a right answer. On the
    # default car the engine's E1 sits on T2, and the imbalance carries some T2
    # at rear-left; that must not add up to a wheel fault on the front axle,
    # which has none. The engine is judged on the sensors that hear it, not
    # diluted by those that cannot.
    Case(
        "bench-engine-front-and-cabin-with-rear-left-imbalance-sweep",
        _sweep(
            *_sized(
                (
                    _ov("front-axle", "engine_order", 0.74, 0.94),
                    _ov("body", "engine_order", 0.42, 0.94),
                    _ov("rear-left", "wheel_imbalance", 0.30, 1.0),
                ),
                _car("i4_with_weak_rl", *_I4_SECOND_ORDER_FORCES, _unbalance("rear-left", _WEAK_G)),
            )
        ),
        _fault("engine", {"engine_bay"}, "E2"),
        second_fault=_fault("wheel/tire", {"rear_left_wheel"}, "T1", dominant_corner=True),
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
                *_ENGINE_FIRST_ORDER_SIZED,
                guided="sweep",
            ),
            _phase(
                "hold",
                6.0,
                100.0,
                100.0,
                *_ENGINE_FIRST_ORDER_SIZED,
                guided="hold",
            ),
            _phase(
                "coast", 10.0, 100.0, 70.0, _ov("all", "engine_idle", 0.2, 0.6), guided="coast_down"
            ),
        ),
        _fault("engine", {"engine_bay"}, "E1", speed_dependence="engine_speed"),
        # On the default car E1 coincides with T2: right source, less certain,
        # unless drive slip moves the engine's tone far enough off T2 for the
        # order evidence to point at E1 itself (see the engine-mount case below).
        {
            "default": _fault(
                "engine",
                {"engine_bay"},
                "E1",
                speed_dependence="engine_speed",
                levels=MODERATE_OR_STRONG,
            )
        },
        idealised_floor=IdealisedFloor.HUMP_SCATTER,
    ),
    # A failing engine mount passes the engine's first order mostly into the
    # front-right corner. On the default car E1 sits on T2, so the order evidence
    # points at that wheel; the coast-down shows it stops in neutral, so it must
    # not be sent to the tire shop.
    Case(
        "bench-guided-engine-mount-front-right",
        _guided(
            *_sized(
                (
                    _ov("all", _ENGINE_FIRST_ORDER.name, 0.25, 0.9),
                    _ov("front-right", _ENGINE_FIRST_ORDER.name, 0.9, 0.9),
                ),
                _car(
                    "engine_first_order_fr_mount",
                    *_ENGINE_FIRST_ORDER_FORCES,
                    coupling={"front-right": 3.6},
                ),
            ),
            coast=(_ov("all", "engine_idle", 0.2, 0.6),),
        ),
        _fault("engine", {"engine_bay"}, "E1", speed_dependence="engine_speed"),
        # On the default car the coast-down shows the T2 the order evidence points
        # at is the engine's E1: right source, less certain. E1 sits only 1.5 %
        # below T2 there, and drive slip moves the engine's tone against the
        # speed reading by about as much: the order evidence may then point at
        # E1 itself, and with the coast-down agreeing it is as certain as on
        # the other car.
        {
            "default": _fault(
                "engine",
                {"engine_bay"},
                "E1",
                speed_dependence="engine_speed",
                levels=MODERATE_OR_STRONG,
            )
        },
    ),
    # One sensor cannot compare corners: a wheel fault, but no wheel named (the
    # sensor's own corner least of all) and never Strong.
    Case(
        "bench-one-sensor-front-left-wheel-sweep",
        _sweep(*_lost_weight("front-left")),
        _fault("wheel/tire", {None}, "T1", levels=MODERATE),
        layout=ONE_SENSOR,
    ),
    # One sensor at the front-left wheel, the imbalance at the rear-right wheel,
    # felt there through the car (tuned: at about a third of its level). Still
    # a wheel fault, never "at the front-left wheel".
    Case(
        "bench-one-sensor-rear-right-imbalance-felt-at-front-left-sweep",
        _sweep(
            *_sized(
                (_ov("front-left", "wheel_imbalance", 0.85 * 0.3, 1.0),),
                _imbalance("rear-right"),
            )
        ),
        _fault("wheel/tire", {None}, "T1", levels=MODERATE),
        layout=ONE_SENSOR,
        idealised_floor=IdealisedFloor.MISSED_UNDER_WHEEL_HOP,
    ),
    # Sensors in the cabin only feel a wheel imbalance through the body: a wheel
    # problem, but no corner can be named and it is never Strong.
    Case(
        "bench-cabin-only-wheel-sweep",
        _sweep(*_sized((_ov("body", "wheel_imbalance", 0.35, 1.0),), _imbalance("front-left"))),
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
    # One wheel sensor plus two in the cabin: the wheel sensor stands out from
    # the cabin, but it would at any faulty wheel: no wheel named, Moderate.
    Case(
        "bench-one-wheel-and-cabin-front-left-wheel-sweep",
        _sweep(
            *_sized(
                (
                    _ov("front-left", "wheel_imbalance", 0.85, 1.0),
                    _ov("body", "wheel_imbalance", 0.12, 1.0),
                ),
                _imbalance("front-left"),
            )
        ),
        _fault("wheel/tire", {None}, "T1", levels=MODERATE),
        layout=ONE_WHEEL_AND_CABIN,
    ),
    # The same with a body that carries the imbalance well into the cabin
    # (tuned: about half the wheel's level there; physically 3.75 times what a
    # rigid body passes): no wheel or axle named, and never the
    # engine order that on the default car shares T2's frequency.
    Case(
        "bench-one-wheel-and-cabin-strong-coupling-sweep",
        _sweep(
            *_sized(
                (
                    _ov("front-left", "wheel_imbalance", 0.85, 1.0),
                    _ov("body", "wheel_imbalance", 0.45, 1.0),
                ),
                _car(
                    "fl_strong_cabin_coupling",
                    _unbalance("front-left", _LOST_WEIGHT_G),
                    coupling={"body": 3.75},
                ),
            )
        ),
        _fault("wheel/tire", {None}, "T1", levels=MODERATE),
        layout=ONE_WHEEL_AND_CABIN,
    ),
    # A front-left imbalance with an even engine tone (tuned: 12 dB under it at
    # that corner; physically a 20 g second-order hum). Scoring spares the
    # engine tone the spread penalty the wheel takes (an engine is a zone), so
    # the tone the whole car shares must not outrank the imbalance. On the other
    # car the tone costs the wheel order part of its matches, so the verdict
    # there is Moderate.
    Case(
        "bench-front-left-wheel-with-engine-hum-sweep",
        _sweep(
            *_sized(
                (
                    _ov("all", "bench_rough_road_engine_hum", 0.28, 0.52),
                    _ov("front-left", "bench_wheel_imbalance_engine_hum", 0.85, 1.0),
                ),
                _car(
                    "fl_with_engine_hum",
                    _unbalance("front-left", _LOST_WEIGHT_G),
                    *_ENGINE_HUM_FORCES,
                ),
            )
        ),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True),
    ),
    # A sensor on every mounting point: road noise everywhere is still no fault,
    # and a wheel fault still stands out at its corner.
    Case("bench-healthy-sweep-every-mount", _sweep(), NO_FAULT, layout=EVERY_MOUNT),
    Case(
        "bench-front-left-wheel-sweep-every-mount",
        _sweep(*_lost_weight("front-left")),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True),
        layout=EVERY_MOUNT,
    ),
    # Idling at a standstill before pulling away (the OBD speed reads 0 km/h):
    # standing still is no speed band, and the wheel fault is still found.
    Case(
        "bench-standstill-pull-away-front-left-wheel",
        (
            _phase("idle", 8.0, 0.0, 0.0),
            _phase("pull_away", 6.0, 0.0, 50.0, *_lost_weight("front-left")),
            *_sweep(*_lost_weight("front-left")),
        ),
        _fault("wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True),
        speed_source="obd2",
    ),
    Case(
        "bench-faint-intermittent-engine",
        (
            _phase("a", 6.0, 75.0, 75.0, *_FAINT_INTERMITTENT_ENGINE),
            _phase("b", 8.0, 75.0, 76.0),
            _phase("c", 6.0, 76.0, 76.0, *_FAINT_INTERMITTENT_ENGINE),
            _phase("d", 8.0, 76.0, 75.0),
        ),
        # Faint and present in under half the drive: found as the engine, never
        # a Strong verdict and never a wheel.
        Expected(
            verdicts=frozenset({"weak_evidence", "fault"}),
            source="engine",
            zones=frozenset({"engine_bay"}),
            # At an almost steady speed the louder E2 tone can pass for a fixed
            # resonance, leaving E1 as the tracked engine order.
            order_codes=frozenset({"E1", "E2"}),
            levels=frozenset({"weak", "moderate"}),
            weak_reasons=_FAINT_ENGINE_REASONS,
        ),
        idealised_floor=IdealisedFloor.MISSED_UNDER_WHEEL_HOP,
    ),
    *GEAR_CASES,
    *ENGINE_PROFILE_CASES,
    *EV_CASES,
    *REALISM_CASES,
    *CONFOUNDER_CASES,
)

SCRIPTED_CASES = (
    _scripted(
        "accel-front-left-surge",
        _fault("wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True),
    ),
    _scripted(
        "coastdown-rear-right-rumble",
        _fault("wheel/tire", {"rear_right_wheel"}, "T1", dominant_corner=True),
        idealised_floor=IdealisedFloor.HUMP_SCATTER,
    ),
    # Every wheel carries the same mild imbalance inside the speed window.
    _scripted(
        "highway-window-shudder",
        _fault("wheel/tire", {"all_wheels"}, "T1", levels=MODERATE),
        idealised_floor=IdealisedFloor.MISSED_UNDER_WHEEL_HOP,
    ),
    _scripted(
        "launch-engine-flare",
        _fault("engine", {"engine_bay"}, "E2"),
        idealised_floor=IdealisedFloor.HUMP_SCATTER,
    ),
    _scripted(
        "pothole-recovery-loop",
        NO_FAULT,
        idealised_floor=IdealisedFloor.HUMP_SCATTER,
    ),
    # Left-side wheels, then right-side wheels: any one wheel, spread evidence,
    # or all four (each side carried the imbalance in turn, and with real tire
    # radii and slip the four wheels' lines no longer coincide exactly, so the
    # spread can read as all four rather than one).
    _scripted(
        "lane-change-left-right",
        _fault("wheel/tire", {*WHEEL_ZONES, "all_wheels"}, "T1", levels=MODERATE),
        idealised_floor=IdealisedFloor.HUMP_SCATTER,
    ),
    _scripted(
        "rear-left-cruise-rumble",
        _fault("wheel/tire", {"rear_left_wheel"}, "T1", dominant_corner=True),
    ),
    _scripted(
        "front-right-cruise-shimmy",
        _fault("wheel/tire", {"front_right_wheel"}, "T1", dominant_corner=True),
        idealised_floor=IdealisedFloor.HUMP_SCATTER,
    ),
    # The driveshaft tone is heard on the rear-axle and trunk sensors, clearly in
    # about half the windows there (as long as the Strong launch-engine-flare).
    _scripted("driveline-coastdown", _fault("driveline", DRIVELINE_ZONES, "P1", levels=MODERATE)),
    # Front-left first, then rear-right: either corner is right.
    _scripted(
        "dual-fault-recovery",
        _fault("wheel/tire", {"front_left_wheel", "rear_right_wheel"}, "T1"),
        idealised_floor=IdealisedFloor.MISSED_UNDER_WHEEL_HOP,
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
    # The imbalance shakes in the brake step's stops too: a wheel, and the brakes
    # checked and ruled out.
    _scripted(
        "guided-brake-stops",
        _fault("wheel/tire", {"front_left_wheel"}, "T1", dominant_corner=True),
        idealised_floor=IdealisedFloor.LEVEL_UNDER_THE_HUMP,
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
        ("bench-one-sensor-rear-right-imbalance-felt-at-front-left-sweep", "default"),
        ("bench-front-brake-judder-stops", "default"),
        ("bench-fwd-front-driveline-sweep", "fwd"),
        ("bench-healthy-sweep", "fwd"),
        ("bench-inline6-firing-top-gear-sweep", "inline_6"),
    }
)
_UNEXPLAINED_HEADLINE_EN = "Vibration found, but no checked cause explains it"
_PDF_HEADLINES = {
    "fault": ("likely cause:", "waarschijnlijke oorzaak:"),
    "weak_evidence": (
        "not enough evidence to name a cause",
        "onvoldoende bewijs om een oorzaak te noemen",
    ),
    "no_fault": ("no significant vibration found", "geen noemenswaardige trilling gevonden"),
}

# The simulator's order keys as (base key, multiple of it): wheel_2x is the
# wheel's 2nd order, engine_2x the crank's.
_TONE_KEYS = {
    "wheel_1x": ("wheel_1x", 1.0),
    "wheel_2x": ("wheel_1x", 2.0),
    "shaft_1x": ("shaft_1x", 1.0),
    "engine_1x": ("engine_1x", 1.0),
    "engine_2x": ("engine_1x", 2.0),
}
_ORDER_BASES = {"T": "wheel_1x", "P": "shaft_1x", "E": "engine_1x"}
_ORDER_SOURCES = {"T": "wheel/tire", "P": "driveline", "E": "engine"}


def _tone(key: str, multiple: float) -> tuple[str, float]:
    """A simulator order tone as (base key, multiple of it); a wheel's tone may name its wheel."""
    base, base_multiple = _TONE_KEYS[key.partition("@")[0]]
    return base, base_multiple * multiple


def _order_keys(profile: Profile) -> list[tuple[str, float]]:
    """Each order tone and force *profile* plays, as ``(order_key, multiple)``."""
    return [(key, multiple) for key, multiple, _amps in profile.order_tones] + [
        (force.order_key, force.multiple) for force in profile.order_forces
    ]


def _order_tone(order_code: str) -> tuple[str, float]:
    """The simulator tone behind an order label: ``E1.5`` is the crank's 1.5th order."""
    return _ORDER_BASES[order_code[0]], float(order_code[1:])


def _engine_multiples(car: BenchCar) -> tuple[float, ...]:
    """The crank orders the car's engine shakes at, from its profile.

    E1 (the crank turning) and the firing rhythm: a four-stroke fires every
    cylinder once per two crank turns, E(n/2). The bench engines' built-in
    imbalance (an inline-3's E1, an inline-4's E2) adds no other order. Without
    a profile E1 and E2; an EV has no engine.
    """
    if car.fuel_type == "EV":
        return ()
    if car.engine_profile is None:
        return (1.0, 2.0)
    return tuple(sorted({1.0, car.engine_profile.cylinders / 2}))


def _engine_code(multiple: float) -> str:
    return f"E{multiple:g}"


def _turns_per_wheel_turn(car: BenchCar, order_code: str, gear: float | None = None) -> float:
    """How often an order repeats per wheel turn, the engine in *gear* (its top gear by default)."""
    multiple = _order_tone(order_code)[1]
    if order_code[0] == "T":
        return multiple
    shaft = multiple * car.final_drive_ratio
    if order_code[0] == "P":
        return shaft
    return shaft * (car.current_gear_ratio if gear is None else gear)


_SIM_MG_PER_COUNT = 1000.0 / 256.0  # ADXL345 full-resolution counts
_FRAME_SAMPLES = 200  # samples per simulated DATA frame (test_support.sim_pipeline)
# A slow, one-sided sync exchange on busy Wi-Fi can step a sensor clock by up to
# half its extra delay (30 ms here).
_MAX_SYNC_STEP_US = 25_000


def injected_order_mg(
    phases: tuple[ScenarioPhase, ...],
    order_code: str,
    layout: tuple[BenchSensor, ...] = SENSORS,
    car: BenchCar = DEFAULT_CAR,
) -> dict[str, float]:
    """Peak order-tone amplitude (mg, 3-axis vector) each location's sensor reads in any phase.

    In a gear that puts an engine order on a wheel or propshaft order, the
    engine's tone is that order's too, and the other way round. A sensor also
    reads the flat spot of the tyre it feels at the start of the drive and an
    engine-driven accessory turning at the order's rhythm, and its fixing's
    resonance amplifies what it reads near it.
    """
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
            car=car.sim_car(CI_SEED),
        )
        for index, sensor in enumerate(layout)
    ]
    injected = {sensor.location_code: 0.0 for sensor in layout}
    for phase in phases:
        tones = _phase_tones(phase, order_code, car)
        apply_phase(clients, "ground-truth", phase)
        speeds = _phase_speeds_kmh(phase)
        for sensor, client in zip(layout, clients, strict=True):
            profile = PROFILE_LIBRARY[client.profile_name]
            counts = sum(
                math.hypot(*amps)
                for key, multiple, amps in profile.order_tones
                if _is_tone(key, multiple, tones)
            )
            counts *= max(profile.order_amplitude_gain(speed) for speed in speeds)
            mg = counts * client.scene_gain * client.amp_scale * _SIM_MG_PER_COUNT
            forces = [
                force
                for force in profile.order_forces
                if _is_tone(force.order_key, force.multiple, tones)
            ]
            if forces:
                forces_mg = max(_order_forces_mg(client, forces, speed) for speed in speeds)
                mg += forces_mg * client.scene_gain * client.amp_scale
            mg += _flat_spot_mg(sensor.flat_spot, car, order_code, phase.gear_ratio)
            mg += _accessory_mg(sensor.accessories, car, order_code, phase.gear_ratio)
            mg *= max(_fixing_gain(sensor.fixing, car, order_code, speed) for speed in speeds)
            injected[sensor.location_code] = max(injected[sensor.location_code], mg)
    return injected


def _order_forces_mg(client: SimClient, forces: list[OrderForce], speed_kmh: float) -> float:
    """Level (mg, 3-axis vector) at which *client* reads *forces* at *speed_kmh*."""
    client.current_speed_kmh = speed_kmh
    return sum(math.hypot(*client.order_force_tone(force)[1]) for force in forces)


def _flat_spot_mg(
    spot: FlatSpot | None, car: BenchCar, order_code: str, gear: float | None
) -> float:
    """A fresh flat spot's level (mg, 3-axis vector) at the order: the wheel
    order it carries that turns at the order's rhythm, if any."""
    if spot is None:
        return 0.0
    turns = _turns_per_wheel_turn(car, order_code, gear)
    return sum(
        math.hypot(*spot.t1_mg) * level
        for n, level in enumerate(spot.harmonic_levels(), start=1)
        if abs(n - turns) <= _ORDER_TOLERANCE_REL * turns
    )


def _accessory_mg(
    accessories: tuple[AccessoryTone, ...], car: BenchCar, order_code: str, gear: float | None
) -> float:
    """Level (mg, 3-axis vector) of the engine-driven accessories at the order's rhythm."""
    if car.fuel_type == "EV":
        return 0.0
    turns = _turns_per_wheel_turn(car, order_code, gear)
    crank = _turns_per_wheel_turn(car, "E1", gear)
    return sum(
        math.hypot(*tone.level_mg)
        for tone in accessories
        if tone.engine_order is not None
        and abs(tone.engine_order * crank - turns) <= _ORDER_TOLERANCE_REL * turns
    )


def _fixing_gain(
    fixing: SensorFixing | None, car: BenchCar, order_code: str, speed_kmh: float
) -> float:
    """How strongly a sensor on *fixing* reads the order at *speed_kmh*: its housing's
    base-excitation transmissibility (1 for a firm one)."""
    if fixing is None or speed_kmh <= 0:
        return 1.0
    r = _order_hz(car, order_code, speed_kmh) / fixing.resonance_hz
    damping = (2.0 * fixing.damping_ratio * r) ** 2
    return math.sqrt((1.0 + damping) / ((1.0 - r * r) ** 2 + damping))


def _is_tone(key: str, multiple: float, tones: set[tuple[str, float]]) -> bool:
    """Whether a profile tone is one of *tones*: the same order, within the order tolerance
    (a wheel on a slightly smaller tire turns a little faster)."""
    base, total = _tone(key, multiple)
    return any(
        base == tone_key and abs(total - tone_multiple) <= _ORDER_TOLERANCE_REL * tone_multiple
        for tone_key, tone_multiple in tones
    )


def _phase_speeds_kmh(phase: ScenarioPhase) -> list[float]:
    """The speeds a phase drives through, a km/h apart."""
    low, high = sorted((phase.speed_start_kmh, phase.speed_end_kmh))
    return [low + step for step in range(int(high - low) + 1)] + [high]


# An order matches within 8 % of its predicted frequency.
_ORDER_TOLERANCE_REL = 0.08


def _order_hz(car: BenchCar, code: str, speed_kmh: float) -> float:
    base, multiple = _order_tone(code)
    return car.order_hz(speed_kmh)[base] * multiple


# Every case runs on one sensor-id seed in default CI; the opt-in matrix repeats
# each case over more seeds (different MACs, so different noise and clock drift).
CI_SEED = 1
MATRIX_SEEDS = (2, 3, 4, 5, 6)
MATRIX_MIN_PASSES = 4


CASE_PARAMS = [
    pytest.param(case, car_key, id=f"{case.case_id}-{car_key}")
    for case in CASES
    if case.physical_only is None or FAULT_AMPLITUDES is FaultAmplitudes.PHYSICAL
    for car_key in case.cars
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
        obd_rpm=case.obd_rpm,
        speed_lag_s=case.speed_lag_s,
        speed_report_period_s=case.speed_report_period_s,
        obd_speed_over_read=case.obd_speed_over_read,
        road=None if case.idealised_floor else generated_road(seed),
    )
    try:
        lossy = bool(case.frame_loss)
        expected = case.expected_for(car_key, result.diagnosis["source"])
        _assert_case(result, car, expected, case)
        assert result.diagnosis["guided_phases"] == [
            step for step in case.guided_steps if step not in case.guided_undetected
        ]
        assert result.diagnosis["guided_phases_undetected"] == list(case.guided_undetected)
        if "coast_down" in case.guided_undetected:
            # A coast-down that never shed speed decides nothing.
            assert result.diagnosis["speed_dependence"] is None
        # The Live page's brake step counts each firm stop the analysis brakes in.
        assert result.guided_brake_stops == case.guided_firm_stops
        if not case.wifi_retry_loss:
            # Congested Wi-Fi may or may not drop a frame for good.
            _assert_frame_integrity(result, lossy=lossy)
        _assert_loose_mount_warnings(result, case)
        if (case.case_id, car_key) in PDF_CASES:
            _assert_pdf_text(result, case, car)
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
        # Nothing the verdict says is not a cause is listed as one.
        assert diagnosis["order_findings"] == [], diagnosis["order_findings"]
        statuses = [check["status"] for check in diagnosis["source_checks"]]
        assert "candidate" not in statuses, diagnosis["source_checks"]
    elif expected.source is None:
        # Hedged guess only: the cause is not part of the expectation.
        assert diagnosis["confidence_level"] in expected.levels, summary
    else:
        assert diagnosis["source"] == expected.source, summary
        assert diagnosis["zone"] in expected.zones, summary
        assert diagnosis["order_code"] in expected.order_codes, summary
        assert diagnosis["confidence_level"] in expected.levels, summary
        _assert_order_frequency(diagnosis, car, case, summary)
        _assert_order_amplitude_mg(diagnosis, case, car)
    if diagnosis["verdict"] != "no_fault":
        _assert_sensor_claims(diagnosis, case, car, summary)
    if diagnosis["source"] == "wheel/tire" and diagnosis["zone"] in _SPREAD_WHEEL_ZONES:
        # Spread over an axle or all four wheels: check first, never "go fix it".
        assert diagnosis["confidence_level"] != "strong", summary
    if expected.dominant_phase is not None:
        assert diagnosis["dominant_phase"] == expected.dominant_phase, summary
    if expected.speed_dependence is not None:
        assert diagnosis["speed_dependence"] == expected.speed_dependence, summary
    if expected.peak_speed_kmh is not None:
        _assert_peak_speed(diagnosis, expected.peak_speed_kmh, summary)
    _assert_spectrum_markers(diagnosis, car, case)
    assert diagnosis["conditions"]["rpm_source"] == _rpm_source(car, case)
    assert [row["code"] for row in diagnosis["conditions"]["engine_orders"]] == [
        _engine_code(multiple) for multiple in _engine_multiples(car)
    ]
    # Without measured RPM an engine order and a road-speed order at the same
    # rhythm in top gear are named together, never Strong.
    alternative = _expected_alternative(car, case, diagnosis)
    assert diagnosis.get("alternative") == alternative, summary
    if alternative is not None:
        assert diagnosis["confidence_level"] != "strong", summary
    engine_alike = _engine_alike(car, case, diagnosis["order_code"])
    if diagnosis["speed_dependence"] != "vehicle_speed":
        # Only measured RPM or a coast-down that keeps it going tells a road-speed
        # order from the engine's in the gear that puts it there: never Strong.
        assert not (engine_alike and diagnosis["confidence_level"] == "strong"), summary
        strong_alike = [
            row["order_code"]
            for row in diagnosis["order_findings"]
            if row["confidence_level"] == "strong" and _engine_alike(car, case, row["order_code"])
        ]
        assert not strong_alike, diagnosis["order_findings"]
    # Brake judder can only be judged on a drive that braked from speed.
    checked = [check["source"] for check in diagnosis["source_checks"]]
    assert checked == ["wheel/tire", "driveline", "engine", "brakes"], checked
    for check in diagnosis["source_checks"]:
        if check["status"] == "candidate" or check["reason"] in _COAST_REASONS:
            continue
        if check["reason"] == "faint_only":
            # Found only at a healthy car's level: the no-fault verdict says so.
            assert diagnosis["verdict"] == "no_fault", diagnosis["source_checks"]
            continue
        expected_check = _expected_check(
            check["source"],
            car,
            case,
            engine_alike=engine_alike,
            candidate=diagnosis["source"],
            alternative=alternative,
        )
        assert (check["status"], check["reason"]) == expected_check, diagnosis["source_checks"]
    _assert_sensor_identity(result)
    _assert_speed_breakdown(result, case)
    _assert_raw_backed(result, case)
    _assert_raw_capture_on_one_clock(result)
    _assert_report_view(result, diagnosis, expected, case, car)
    _assert_felt(diagnosis, case, car)
    if diagnosis["verdict"] == "weak_evidence":
        assert expected.weak_reasons <= set(diagnosis["weak_reasons"]), summary
        assert len(result.report.owner.reasons) == len(diagnosis["weak_reasons"]) > 0
    if diagnosis["verdict"] == "fault":
        _assert_speed_chart(result, diagnosis, car, case, expected)


def _assert_sensor_claims(diagnosis: dict, case: Case, car: BenchCar, summary: str) -> None:
    """A corner or an axle is named only where the sensors could compare them.

    One wheel sensor feels a fault at any wheel, strongest where it sits; with
    one sensor nothing is compared at all, and the report says so.
    """
    source, zone = diagnosis["source"], diagnosis["zone"]
    axles = {"front_axle", "rear_axle"}
    if source == "wheel/tire" and not case.corners_compared:
        assert zone not in WHEEL_ZONES | axles | {"all_wheels"}, summary
    if source == "brakes" and not case.axles_compared:
        assert zone is None, summary
    if source == "driveline" and not case.axles_compared:
        # Where the drive layout puts the shaft: the driven axle without a propshaft.
        assert zone not in axles or (car.drive_layout == "FWD" and zone == "front_axle"), summary
    if len(case.layout) == 1:
        assert "single_sensor" in diagnosis["weak_reasons"], summary
        assert "spread_across_locations" not in diagnosis["weak_reasons"], summary


def _rpm_source(car: BenchCar, case: Case) -> str:
    """An EV has no engine RPM; otherwise it is the OBD's, or estimated from speed in top gear."""
    if car.fuel_type == "EV":
        return "none"
    return "measured" if case.obd_rpm else "estimated_top_gear"


def _engine_alike(car: BenchCar, case: Case, order_code: str | None) -> bool:
    """Whether some gear puts an engine order on this wheel or propshaft order.

    Without measured RPM the drive may have been in any gear: in gear ``g`` the
    engine's ``m``-th order repeats ``m * g * final drive`` times per wheel
    turn, and a lower gear has a higher ratio than the top gear.
    """
    if case.obd_rpm or order_code is None or order_code[0] == "E":
        return False
    per_wheel_turn = _turns_per_wheel_turn(car, order_code)
    lowest_gear = car.current_gear_ratio * (1.0 - _ORDER_TOLERANCE_REL)
    return any(
        per_wheel_turn / (multiple * car.final_drive_ratio) >= lowest_gear
        for multiple in _engine_multiples(car)
    )


def _expected_alternative(car: BenchCar, case: Case, diagnosis: dict) -> dict | None:
    """The other order at the diagnosed one's rhythm in top gear, when nothing told them apart.

    RPM estimated from the speed puts the engine in top gear: an engine order
    within the order tolerance of a wheel or propshaft order there is the same
    peaks. Measured RPM or a neutral coast-down that decided tells them apart.
    """
    code = diagnosis["order_code"]
    if (
        diagnosis["verdict"] == "no_fault"
        or code is None
        or case.obd_rpm
        or diagnosis["speed_dependence"] is not None
        or not car.final_drive_entered
    ):
        return None
    engine_codes = [_engine_code(multiple) for multiple in _engine_multiples(car)]
    others = ["T1", "T2", "P1", "P2"] if code[0] == "E" else engine_codes
    turns = _turns_per_wheel_turn(car, code)
    alike = []
    for other in others:
        other_turns = _turns_per_wheel_turn(car, other)
        engine_turns = turns if code[0] == "E" else other_turns
        if abs(other_turns - turns) <= _ORDER_TOLERANCE_REL * engine_turns:
            alike.append((abs(other_turns - turns), other))
    if not alike:
        return None
    other = min(alike)[1]
    return {"source": _ORDER_SOURCES[other[0]], "order_code": other}


def _expected_check(
    source: str,
    car: BenchCar,
    case: Case,
    *,
    engine_alike: bool,
    candidate: str,
    alternative: dict | None = None,
) -> tuple[str, str]:
    """How a source the run did not blame is checked off.

    The bench car's references are the user's own and the simulator's speed is
    the true speed, so wheels and driveline are ruled out outright, unless the
    car has no final drive to place the driveline orders. An engine no-match on
    RPM estimated in top gear is never a plain "ruled out", and is no test at
    all when some gear puts an engine order on the diagnosed one; an EV has no
    engine. Brake judder can only be judged on a drive that braked from speed
    (an EV or PHEV may have braked on regeneration alone, so only with a hedge),
    and a wheel order heard only while braking is the brakes, not a wheel. The
    source the diagnosis names as the other possible cause is not told apart.
    """
    if alternative is not None and source == alternative["source"]:
        return ("not_testable", "same_rhythm_as_candidate")
    if source == "brakes" and not case.brakes_firmly:
        return ("not_testable", "no_braking")
    if source == "brakes" and car.fuel_type in ("EV", "PHEV"):
        # Regenerative braking may have slowed the car without the discs.
        return ("ruled_out_estimated", "regen_braking")
    if source == "wheel/tire" and candidate == "brakes":
        return ("ruled_out", "only_while_braking")
    if source == "engine":
        if car.fuel_type == "EV":
            return ("not_applicable", "electric_car")
        if engine_alike:
            return ("not_testable", "same_rhythm_as_candidate")
        if not case.obd_rpm:
            return ("ruled_out_estimated", "top_gear_assumed")
    elif source == "driveline" and not car.final_drive_entered:
        return ("not_testable", "no_drive_reference")
    return ("ruled_out", "no_matching_order")


def _assert_order_amplitude_mg(diagnosis: dict, case: Case, car: BenchCar) -> None:
    """The strongest location's mg level is on the scale of the tone the simulator injected.

    It is the order's tracked level: the band power over the local floor at its
    line, averaged over the windows at the speeds it was heard and read over the
    line's sweep while the speed changes. A tone on one axis of the combined
    spectrum reads a fraction of the injected peak, and the road's floor
    partly hides a faint one; a unit error is off by 10x or more.
    """
    assert diagnosis["amplitude_basis"] == "order"
    strongest = diagnosis["location_amplitudes"][0]
    code = location_code_for_label(strongest["location"])
    injected = injected_order_mg(case.phases, diagnosis["order_code"], case.sensors(), car)[code]
    assert injected > 0, (strongest, diagnosis["order_code"])
    assert injected / 40.0 <= strongest["amplitude_mg"], (strongest, injected)
    fixing = case.fixings.get(code)
    if fixing is None or fixing.rattle_g is None:
        # A rattling sensor's landings add broadband energy to every band.
        assert strongest["amplitude_mg"] <= injected / 3.0, (strongest, injected)


def _assert_felt(diagnosis: dict, case: Case, car: BenchCar) -> None:
    """The causes are ranked by what the simulator injected where the occupants sit.

    The felt reference is the layout's sensor nearest the occupants (a seat,
    then the trunk, then the propshaft tunnel), unless that sensor lost frames.
    A cause the reference measures has an order injected there, and none it
    measures got more than twice as much injected there as the first. A
    no-fault run lists no cause.
    """
    felt = diagnosis["felt"]
    if diagnosis["verdict"] == "no_fault":
        assert felt["causes"] == [], felt
    sensors = case.sensors()
    present = {sensor.location_code for sensor in sensors}
    nearest = next((code for code in FELT_LOCATIONS if code in present), None)
    if felt["reference"] is None:
        # A sensor that lost frames may have no order levels to read.
        assert (
            nearest is None or nearest in case.frame_loss or felt["fallback"] == "no_order_levels"
        ), felt
        return
    assert location_code_for_label(felt["reference"]) == nearest, felt
    injected = [
        math.hypot(
            *(
                injected_order_mg(case.phases, code, sensors, car)[nearest]
                for code in row["order_codes"]
            )
        )
        for row in felt["causes"]
        if row["level_mg"] > 0
    ]
    assert all(mg > 0 for mg in injected), (felt, injected)
    assert all(mg <= 2.0 * injected[0] for mg in injected), (felt, injected)
    # One injected tone is one cause there: an engine order the drive's gear
    # puts on a wheel order is one line, never counted for both.
    tones = [
        {
            tone
            for code in row["order_codes"]
            for phase in case.phases
            for tone in _phase_tones(phase, code, car)
        }
        for row in felt["causes"]
        if row["level_mg"] > 0
    ]
    for index, own in enumerate(tones):
        assert all(own.isdisjoint(other) for other in tones[index + 1 :]), felt


def _phase_tones(phase: ScenarioPhase, order_code: str, car: BenchCar) -> set[tuple[str, float]]:
    """The simulator tones at *order_code* in *phase*: its own, and those of the
    engine or road-speed orders the phase's gear puts on it (the car's own gear
    unless the phase names one)."""
    tones = {_order_tone(order_code)}
    if car.fuel_type == "EV" or not car.final_drive_entered:
        return tones
    turns = _turns_per_wheel_turn(car, order_code, phase.gear_ratio)
    engine_codes = [_engine_code(multiple) for multiple in _engine_multiples(car)]
    others = ["T1", "T2", "P1", "P2"] if order_code[0] == "E" else engine_codes
    for other in others:
        other_turns = _turns_per_wheel_turn(car, other, phase.gear_ratio)
        if abs(other_turns - turns) <= _ORDER_TOLERANCE_REL * turns:
            tones.add(_order_tone(other))
    return tones


def injected_sweep_kmh(
    phases: tuple[ScenarioPhase, ...],
    order_code: str,
    car: BenchCar,
    *,
    visible_from_kmh: float = 0.0,
    flat_spot: FlatSpot | None = None,
) -> float:
    """Widest steady speed sweep (km/h, over 8 s or more) while the order's tone was injected.

    Only the part of a sweep above *visible_from_kmh* counts: below it the
    order's tone is under the lowest frequency the analysis looks at. A
    *flat_spot* shakes at its wheel orders, and at what turns at their rhythm,
    through the whole drive.
    """
    return max(
        (
            max(phase.speed_end_kmh, phase.speed_start_kmh)
            - max(min(phase.speed_end_kmh, phase.speed_start_kmh), visible_from_kmh)
            for phase in phases
            if phase.duration_s >= 8.0
            and (
                _flat_spot_mg(flat_spot, car, order_code, phase.gear_ratio) > 0
                or any(
                    _is_tone(key, multiple, _phase_tones(phase, order_code, car))
                    for override in phase.overrides
                    for key, multiple in _order_keys(PROFILE_LIBRARY[override.profile_name])
                )
            )
        ),
        default=0.0,
    )


def _assert_speed_chart(
    result: SimPipelineResult, diagnosis: dict, car: BenchCar, case: Case, expected: Expected
) -> None:
    """Amplitude vs speed is charted when the fault was swept over a speed range."""
    chart = result.report.mechanic.speed_chart
    order_code = diagnosis["order_code"]
    # A wheel order at walking pace is far below the analysed band (5 Hz and up).
    visible_from = MIN_ANALYSIS_FREQ_HZ / (_order_hz(car, order_code, 100.0) / 100.0)
    span = injected_sweep_kmh(
        case.phases,
        order_code,
        car,
        visible_from_kmh=visible_from,
        flat_spot=next(iter(case.flat_spots.values()), None),
    )
    if span >= 40.0:
        assert chart is not None, span
        assert [series.strongest for series in chart.series][:1] == [True]
        if expected.dominant_corner:
            # The highlighted curve is the faulty corner's, the loudest one.
            peaks = [max(amp for _speed, amp in series.points) for series in chart.series]
            assert peaks[0] == max(peaks), (chart.series[0].label, peaks)


def _assert_peak_speed(diagnosis: dict, band_kmh: tuple[float, float], summary: str) -> None:
    """The report names the speeds where the order shakes hardest.

    The description's speed (the median matched speed in the loudest 10 km/h
    band) sits within half a band of it, and the top of the strongest
    location's amplitude-vs-speed curve (5 km/h bins) within half a bin.
    """
    low, high = band_kmh
    assert low - 5.0 <= diagnosis["reference_speed_kmh"] <= high + 5.0, summary
    strongest = diagnosis["location_amplitudes"][0]["location"]
    curve = [
        (point["amplitude_mg"], point["speed_kmh"])
        for point in diagnosis["amplitude_vs_speed"]
        if point["location"] == strongest
    ]
    assert curve, diagnosis["amplitude_vs_speed"]
    peak_kmh = max(curve)[1]
    assert low - 2.5 <= peak_kmh <= high + 2.5, (peak_kmh, curve)


def _assert_order_frequency(diagnosis: dict, car: BenchCar, case: Case, summary: str) -> None:
    """The reported frequency follows the order at the reported speed (own tire/ratio math).

    Spectra average ~2.5 s, so on a speed ramp the measured Hz per km/h lags by a
    few percent; a wrong order or tire size is off by 10 % or more. An engine
    order may sit in any gear the drive used.
    """
    speed = diagnosis["reference_speed_kmh"]
    frequency = diagnosis["frequency_hz"]
    assert speed is not None and frequency is not None, summary
    gears = {car.current_gear_ratio} | {
        phase.gear_ratio for phase in case.phases if phase.gear_ratio is not None
    }
    expected_hz = [
        _order_hz(replace(car, current_gear_ratio=gear), diagnosis["order_code"], speed)
        for gear in sorted(gears)
    ]
    assert any(frequency == pytest.approx(hz, rel=0.06) for hz in expected_hz), summary


def _assert_spectrum_markers(diagnosis: dict, car: BenchCar, case: Case) -> None:
    """The spectrum marks each order the car's references place, and no other.

    Without a final drive no propshaft or motor order is placed; an EV has no
    engine orders; measured RPM places them in whatever gear the car was in.
    """
    spectrum = diagnosis["spectrum"]
    if spectrum is None:
        return
    markers = spectrum["order_markers"]
    # A wheel sensor's wheel orders turn with its own axle's tires; the
    # propshaft with the rear's (the speed reference).
    axle = wheel_axle(spectrum["location"])
    low = car.wheel_hz(spectrum["speed_min_kmh"], axle)
    high = car.wheel_hz(spectrum["speed_max_kmh"], axle)
    assert low * 0.98 <= markers["T1"] <= high * 1.02, markers
    assert markers["T2"] == pytest.approx(2.0 * markers["T1"], rel=1e-6)
    engine_markers = {code for code in markers if code.startswith("E")}
    if not car.final_drive_entered:
        assert not {"P1", "P2"} & set(markers) and not engine_markers, markers
        return
    rear_wheel = markers["T1"] * car.tire_circumference_m(axle) / car.tire_circumference_m()
    assert markers["P1"] == pytest.approx(car.final_drive_ratio * rear_wheel, rel=1e-6)
    assert markers["P2"] == pytest.approx(2.0 * markers["P1"], rel=1e-6)
    # The engine's own orders: E1 and its firing rhythm (E1/E2 when not known).
    multiples = _engine_multiples(car)
    assert engine_markers == {_engine_code(multiple) for multiple in multiples}, markers
    if not multiples:
        return
    if not case.obd_rpm:
        assert markers["E1"] == pytest.approx(car.current_gear_ratio * markers["P1"], rel=1e-6)
    for multiple in multiples:
        code = _engine_code(multiple)
        assert markers[code] == pytest.approx(multiple * markers["E1"], rel=1e-6)


def _assert_loose_mount_warnings(result: SimPipelineResult, case: Case) -> None:
    """The report says a sensor may be loose when it turned on its fixing, never when it held."""
    warnings = " ".join(result.report.quality.warnings)
    for location, turn_deg in result.mount_turn_deg.items():
        warning = f"The {tr('en', f'LOC_{location.upper()}')} sensor may be loosely mounted"
        if location in case.loose_mounts:
            assert warning in warnings, (location, turn_deg, warnings)
        elif turn_deg < _UNNOTICED_TURN_DEG:
            assert warning not in warnings, (location, turn_deg, warnings)


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
        starts = sorted(sensor.chunks.t0_us.tolist())
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
        # A lossy sensor's frame gaps leave most of its rows to the stored
        # summaries; the other sensors' rows replay from raw samples.
        intact = sum(1 for sensor in case.sensors() if not sensor.frame_loss) / len(case.layout)
        assert raw_backed >= 0.75 * intact * total, metadata
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
_MOTOR_NO_RATIO_LINE = "Electric motor: not testable: no reduction ratio"
_ENGINE_SAME_RHYTHM_TEXT = (
    "Without measured engine RPM this can also be the engine: in some gear it turns at this"
    " same rhythm."
)
# A diagnosis that names a second cause at the same rhythm says so.
_HEDGE_TEXT = "Without measured engine RPM it cannot be told apart from"
_COAST_REASONS = ("stayed_in_neutral", "stopped_in_neutral")
_SPEED_SOURCE_TEXT = {"gps": "GPS", "obd2": "OBD"}
_SOURCE_NAMES_EN = {
    "wheel/tire": "Wheels/tires",
    "driveline": "Driveline",
    "engine": "Engine",
    "brakes": "Brakes",
}
# An EV's driveline is its electric drive unit.
_EV_SOURCE_NAMES_EN = {**_SOURCE_NAMES_EN, "driveline": "Electric motor"}
# Brake judder sends the owner to the brake discs on the axle that judders.
_BRAKE_DISCS = {
    "front_axle": ("front brake discs", "remschijven voor"),
    "rear_axle": ("rear brake discs", "remschijven achter"),
}

# What the owner is told to have checked, per diagnosed order.
_NEXT_STEP_KEYWORDS = {"T1": "balanced", "T2": "out-of-round"}
# Every engine order sends the owner to the engine and gearbox mounts.
_ENGINE_NEXT_STEP_KEYWORD = "mounts"
_EV_NEXT_STEP_KEYWORDS = {**_NEXT_STEP_KEYWORDS, "P1": "drive unit"}
# A driveline fault's advice follows the drive layout: a car without a propshaft
# is sent to its gearbox output shaft; without a layout the propshaft advice
# stays and the report says the layout was not given.
_DRIVELINE_NEXT_STEP = {
    "FWD": ("gearbox output shaft",),
    "RWD": ("propshaft",),
    "AWD": ("front propshaft", "propshaft to the rear axle"),
    None: ("propshaft", "drive layout was not given"),
}
_DRIVE_LAYOUT_TEXT = {
    "FWD": "front-wheel drive",
    "RWD": "rear-wheel drive",
    "AWD": "all-wheel drive",
    None: "not provided",
}


def _assert_report_view(
    result: SimPipelineResult, diagnosis: dict, expected: Expected, case: Case, car: BenchCar
) -> None:
    # The mechanic's worksheet lists each order once; where it was strongest is
    # in the per-location table.
    worksheet_orders = [row.order for row in result.report.mechanic.worksheet]
    assert len(worksheet_orders) == len(set(worksheet_orders)), worksheet_orders
    if case.obd_rpm:
        # Measured RPM tells the engine's tone from a road-speed order it passes
        # in one gear: the worksheet lists only orders the drive really carried.
        carried = {
            _tone(key, multiple)[0]
            for phase in case.phases
            for override in phase.overrides
            for key, multiple in _order_keys(PROFILE_LIBRARY[override.profile_name])
        }
        listed = {row["order_code"] for row in diagnosis["order_findings"]}
        uncarried = {code for code in listed if _order_tone(code)[0] not in carried}
        assert uncarried == set(), f"not in the drive: {sorted(uncarried)} of {sorted(listed)}"
    owner = result.report.owner
    assert owner.verdict == diagnosis["verdict"]
    assert owner.level == diagnosis["confidence_level"]
    conditions = {fact.label: fact.value for fact in result.report.mechanic.conditions}
    assert conditions["Speed source"] == _SPEED_SOURCE_TEXT[case.speed_source], conditions
    engine_check = next(c for c in diagnosis["source_checks"] if c["source"] == "engine")
    electric = car.fuel_type == "EV"
    if not electric:
        layout_text = _DRIVE_LAYOUT_TEXT[car.drive_layout]
        assert conditions["Drive layout"].startswith(layout_text), conditions
    if car.drive_layout == "FWD":
        assert propshaft_mentions(report_view_texts(result.report)) == []
    if car.drive_layout is not None:
        # Drive shafts and CV joints turn at wheel speed, never at a driveline order.
        assert wheel_speed_part_mentions(report_view_texts(result.report)) == []
    if electric and not car.final_drive_entered:
        # The motor's own ratio is missing, not a final drive.
        assert _MOTOR_NO_RATIO_LINE in result.report.mechanic.ruled_out
    # The owner is told when the engine could not be told apart from the cause:
    # by name when it turns at the same rhythm in top gear.
    alternative = diagnosis.get("alternative")
    same_rhythm = engine_check["reason"] == "same_rhythm_as_candidate" and alternative is None
    assert (_ENGINE_SAME_RHYTHM_TEXT in owner.description) is same_rhythm, owner.description
    assert (_HEDGE_TEXT in owner.description) is (alternative is not None), owner.description
    if alternative is not None:
        cause = owner.headline if diagnosis["verdict"] == "fault" else owner.candidate
        assert cause is not None and f"({alternative['order_code']})" in cause, cause
    # The engine the run tested: its layout and firing order when known.
    if electric:
        assert "Engine" not in conditions, conditions
    elif car.engine_profile is None:
        assert conditions["Engine"] == "not known: E1 and E2 tested", conditions
    else:
        firing = _engine_code(car.engine_profile.cylinders / 2)
        assert conditions["Engine"].endswith(f"fires at {firing}"), conditions
    # A known engine's firing rhythm is analysed; without one a six's is not.
    never = next((item for item in owner.not_covered if item.startswith("Never analysed")), None)
    if never is not None:
        assert ("six-cylinder" in never) is (car.engine_profile is None and not electric), never
    if engine_check["reason"] == "top_gear_assumed":
        # The workshop is told the engine check assumed top gear.
        assert _ENGINE_TOP_GEAR_LINE in result.report.mechanic.ruled_out
    if diagnosis["verdict"] == "no_fault":
        # A strong shake that no order explains is reported as found, not as
        # nothing found; a healthy car's road noise is not significant.
        nothing_found = owner.headline == "No significant vibration found"
        if expected.unexplained_vibration:
            assert not nothing_found, owner.headline
            assert owner.headline == _UNEXPLAINED_HEADLINE_EN, owner.headline
        else:
            assert nothing_found, owner.headline
        assert owner.diagram.zone is None
        # What the drive did not cover: without measured engine RPM the engine was
        # untested or checked in top gear only, and a drive that never went below
        # 40 km/h says so.
        not_covered = owner.not_covered
        engine_gap = any(item.startswith("Engine: ") for item in not_covered)
        assert engine_gap is (_rpm_source(car, case) == "estimated_top_gear"), not_covered
        lowest_kmh = min(min(p.speed_start_kmh, p.speed_end_kmh) for p in case.phases)
        below = any(item.startswith("Speeds below") for item in not_covered)
        assert below is (lowest_kmh >= 40.0), not_covered
        # A coast-down is not braking: without firm braking from speed the report
        # says brake judder was not checked. An EV or PHEV may have stopped on
        # regeneration alone, so its brake check stays open either way.
        braking_gap = [item for item in not_covered if "brak" in item.lower()]
        regen = car.fuel_type in ("EV", "PHEV")
        assert bool(braking_gap) is (regen or not case.brakes_firmly), not_covered
        return
    cause_text = owner.headline if diagnosis["verdict"] == "fault" else owner.candidate
    assert cause_text is not None
    zone_text = _ZONE_TEXT_EN.get(diagnosis["zone"])
    if diagnosis["source"] == "wheel/tire":
        # Both wheels of an axle are named as wheels, not as the axle.
        zone_text = _WHEEL_AXLE_TEXT_EN.get(diagnosis["zone"], zone_text)
    if zone_text is not None:
        assert zone_text in cause_text, cause_text
    unlocated_wheel = diagnosis["source"] == "wheel/tire" and not case.corners_compared
    if unlocated_wheel:
        not_pinned, felt_at, mount_sensors = _UNLOCATED_WHEEL_TEXT["en"]
        assert not_pinned in cause_text, cause_text
        felt_where = (
            _ONLY_WHEEL_SENSOR_TEXT["en"]
            if diagnosis["zone"] is None
            else felt_at.format(_CABIN_TEXT[diagnosis["zone"]][0])
        )
        assert felt_where in cause_text, cause_text
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
        source_name = (_EV_SOURCE_NAMES_EN if electric else _SOURCE_NAMES_EN).get(
            diagnosis["source"]
        )
        ruled_out = result.report.mechanic.ruled_out
        assert not any(line.startswith(f"{source_name}:") for line in ruled_out), ruled_out
        assert owner.verify is not None
        assert f"{diagnosis['order_code']} " in owner.verify
        assert owner.verify.rstrip(".").endswith("mg today")
        if diagnosis["source"] == "brakes":
            # The brake discs, not a wheel to balance.
            assert _BRAKE_DISCS[diagnosis["zone"]][0] in owner.next_step, owner.next_step
            assert "balance" not in owner.next_step, owner.next_step
        elif diagnosis["source"] == "driveline" and not electric:
            # The parts to check follow the drive layout.
            for keyword in _DRIVELINE_NEXT_STEP[car.drive_layout]:
                assert keyword in owner.next_step, owner.next_step
        else:
            code = diagnosis["order_code"]
            keyword = (_EV_NEXT_STEP_KEYWORDS if electric else _NEXT_STEP_KEYWORDS).get(
                code, _ENGINE_NEXT_STEP_KEYWORD if code and code[0] == "E" else None
            )
            if keyword is not None and not unlocated_wheel:
                assert keyword in owner.next_step, owner.next_step
    if expected.dominant_corner and diagnosis["verdict"] == "fault":
        corner = _ZONE_TEXT_EN[diagnosis["zone"]]
        # The order's own level at the next sensor can read nothing over its floor
        # (a corner's imbalance does not reach the other knuckles over their road
        # noise): then there is no ratio to state, only where it is measurable.
        # Over a short stretch on a rough road no sensor's level may stand out
        # of the road's scatter: then only the matched peaks place the corner,
        # strongest, with no ratio either.
        assert (
            f"stronger at the {corner} than at the next sensor" in owner.description
            or f"measurable only at the {corner}," in owner.description
            or f"strongest at the {corner}," in owner.description
        ), owner.description


def _assert_pdf_text(result: SimPipelineResult, case: Case, car: BenchCar) -> None:
    verdict = result.diagnosis["verdict"]
    unlocated_wheel = result.diagnosis["source"] == "wheel/tire" and not case.corners_compared
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
            zone = result.diagnosis["zone"]
            felt_where = (
                _ONLY_WHEEL_SENSOR_TEXT[lang]
                if zone is None
                else felt_at.format(_CABIN_TEXT[zone][lang == "nl"])
            )
            for text in (not_pinned, felt_where, mount_sensors):
                assert text in pages[0], (text, pages[0][:400])
        if verdict == "fault":
            assert view.owner.next_step.lower()[:40] in pages[0]
            assert view.owner.verify is not None
        if result.diagnosis["source"] == "brakes":
            discs = _BRAKE_DISCS[result.diagnosis["zone"]][lang == "nl"]
            assert discs in pages[0], pages[0][:400]
        if car.drive_layout == "FWD":
            assert propshaft_mentions(pages) == []
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


def test_gentle_firm_stops_count_on_a_late_one_hz_gps(tmp_path: Path) -> None:
    """The firm-stops step at its gentlest, 0.2 g from 80 to 20 km/h (8.5 s), on a 1 Hz GPS.

    The fixes come 0.8 s late, and the recorder flushes every 0.268 s (as the
    Pi did before its flush loop kept deadlines), so each new speed lands on an
    irregular tick, as when a fix's latency varies. The Live count has each
    stop, and the analysis brakes in each.
    """
    stop_s = 60.0 / (0.2 * 9.80665 * 3.6)
    phases = [_phase("brake-speed-up", 6.0, 70.0, 80.0, guided="brake")]
    for stop in range(3):
        phases += [
            _phase(f"brake-steady-{stop}", 4.0, 80.0, 80.0, guided="brake"),
            _phase(f"brake-{stop}", stop_s, 80.0, 20.0, guided="brake"),
            _phase(f"brake-speed-up-{stop}", 8.0, 20.0, 80.0, guided="brake"),
        ]
    result = run_sim_pipeline(
        tmp_path,
        car=DEFAULT_CAR,
        sensors=SENSORS,
        scenario_name="gentle-firm-stops",
        phases=tuple(phases),
        client_seed=CI_SEED,
        speed_lag_s=0.8,
        speed_report_period_s=1.0,
        flush_period_s=0.268,
    )
    try:
        assert result.guided_brake_stops == 3
        samples = [
            frame for batch in result.history_db.iter_run_samples(result.run_id) for frame in batch
        ]
        segments = segment_run_phases(samples)[1]
        braking = [seg for seg in segments if seg.phase is DrivingPhase.BRAKING]
        assert len(braking) == 3, [(seg.start_t_s, seg.end_t_s) for seg in braking]
    finally:
        result.history_db.close()


def test_a_drive_cut_off_before_stop_is_recovered_and_diagnosed(tmp_path: Path) -> None:
    """The ignition cuts the Pi's power mid-drive: the next start analyses what was saved.

    The run is not lost as an error: startup ends it at its last saved sample,
    rebuilds its raw capture from the files on disk and analyses it from raw
    replay, with the same diagnosis as a drive stopped normally, and the report
    says the recording was cut off.
    """
    fault = _FL_IMBALANCE
    phases = (*_sweep(*fault), _phase("cruise", 13.0, 70.0, 70.0, *fault))
    result = run_sim_pipeline(
        tmp_path,
        car=DEFAULT_CAR,
        sensors=SENSORS,
        scenario_name="power-cut-drive",
        phases=phases,
        client_seed=CI_SEED,
        cut_power=True,
    )
    try:
        assert result.metadata.interrupted
        run = result.history_db.get_run(result.run_id)
        assert run is not None and run.status == "complete"
        assert run.end_time_utc is not None
        payload = result.analysis.payload
        assert payload["duration_s"] == pytest.approx(35.0, abs=1.5)
        assert payload["analysis_metadata"]["raw_capture_mode"] == "raw_backed"
        diagnosis = result.diagnosis
        assert (diagnosis["verdict"], diagnosis["source"], diagnosis["zone"]) == (
            "fault",
            "wheel/tire",
            "front_left_wheel",
        )
        assert "recording_interrupted" in {warning["code"] for warning in payload["warnings"]}
        assert any("power was lost" in warning for warning in result.report.quality.warnings)
    finally:
        result.history_db.close()


def test_recording_stops_at_the_configured_cap_and_is_still_analysed(tmp_path: Path) -> None:
    fault = _FL_IMBALANCE
    phases = (*_sweep(*fault), _phase("cruise", 13.0, 70.0, 70.0, *fault))
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


def _rows(result: SimPipelineResult) -> list[SensorFrame]:
    return [frame for batch in result.history_db.iter_run_samples(result.run_id) for frame in batch]


# A typed-in fallback speed none of these drives holds, so a recorded one would show.
_FALLBACK_KMH = 50.0


@pytest.mark.parametrize("speed_source", ["gps", "obd2"])
def test_a_live_speed_dropout_is_recorded_as_unknown_not_as_the_fallback_speed(
    tmp_path: Path, speed_source: SpeedSource
) -> None:
    fault = _FL_IMBALANCE
    phases = (*_sweep(*fault), _phase("cruise", 13.0, 70.0, 70.0, *fault))
    result = run_sim_pipeline(
        tmp_path,
        car=DEFAULT_CAR,
        sensors=SENSORS,
        scenario_name="speed-dropout",
        phases=phases,
        client_seed=CI_SEED,
        speed_source=speed_source,
        fallback_speed_kmh=_FALLBACK_KMH,
        speed_dropout_s=(24.0, 31.0),
    )
    try:
        rows = _rows(result)
        assert {row.speed_source for row in rows} == {speed_source, f"{speed_source}_unaligned"}
        lost = [row for row in rows if 26.0 <= row.t_s <= 31.0]
        assert lost and all(row.speed_kmh is None for row in lost), lost[0]
        assert all(row.speed_source == f"{speed_source}_unaligned" for row in lost)
        diagnosis = result.diagnosis
        assert (diagnosis["verdict"], diagnosis["source"], diagnosis["zone"]) == (
            "fault",
            "wheel/tire",
            "front_left_wheel",
        )
        source_name = "GPS" if speed_source == "gps" else "OBD-II"
        gap = [w for w in result.analysis.payload["warnings"] if w["code"] == "speed_missing"]
        assert len(gap) == 1, result.analysis.payload["warnings"]
        stated = " ".join(result.report.quality.warnings)
        # 7 s without a report; a window within a second of one still has its speed.
        assert re.search(f"{source_name} speed was missing for [56] s of the recording", stated), (
            stated
        )
    finally:
        result.history_db.close()


def test_a_drive_started_before_the_gps_has_a_fix_records_no_speed_until_it_has(
    tmp_path: Path,
) -> None:
    fault = _FL_IMBALANCE
    phases = (*_sweep(*fault), _phase("cruise", 13.0, 70.0, 70.0, *fault))
    result = run_sim_pipeline(
        tmp_path,
        car=DEFAULT_CAR,
        sensors=SENSORS,
        scenario_name="gps-cold-start",
        phases=phases,
        client_seed=CI_SEED,
        fallback_speed_kmh=_FALLBACK_KMH,
        speed_dropout_s=(0.0, 8.0),
    )
    try:
        rows = _rows(result)
        early = [row for row in rows if row.t_s <= 8.0]
        assert early and all(row.speed_kmh is None for row in early), early[0]
        assert all(row.speed_source == "gps_unaligned" for row in early)
        assert all(row.speed_kmh is not None for row in rows if row.t_s >= 10.0)
    finally:
        result.history_db.close()


def test_a_stop_is_recorded_at_zero_speed(tmp_path: Path) -> None:
    """A 1 Hz GPS reports the stop; its first 0.0 fixes are recorded, not a gap."""
    phases = (
        _phase("cruise", 6.0, 80.0, 80.0),
        _phase("brake", 6.0, 80.0, 0.0),
        _phase("stopped", 6.0, 0.0, 0.0),
        _phase("drive-off", 8.0, 0.0, 60.0),
        _phase("cruise-again", 10.0, 60.0, 60.0),
    )
    result = run_sim_pipeline(
        tmp_path,
        car=DEFAULT_CAR,
        sensors=SENSORS,
        scenario_name="stop",
        phases=phases,
        client_seed=CI_SEED,
        fallback_speed_kmh=_FALLBACK_KMH,
        speed_report_period_s=1.0,
    )
    try:
        rows = _rows(result)
        assert {row.speed_source for row in rows} == {"gps"}
        # Stopped from 12 s to 18 s; a row's speed is that of its analysis window.
        stopped = [row for row in rows if 13.5 <= row.t_s <= 18.0]
        assert stopped and all(row.speed_kmh == 0.0 for row in stopped), [
            (row.t_s, row.speed_kmh) for row in stopped
        ]
    finally:
        result.history_db.close()


@pytest.mark.parametrize(
    ("dropout_s", "faults"),
    [
        # The GPS never had a fix: no speed at all.
        pytest.param((0.0, 100.0), (), id="no-fix-healthy-car"),
        # A fix only for the last 7 s: too little speed to place any rhythm.
        pytest.param(
            (0.0, 28.0),
            _FL_IMBALANCE,
            id="late-fix-wheel-fault",
        ),
    ],
)
def test_a_run_without_live_speed_for_most_of_it_could_check_nothing(
    tmp_path: Path, dropout_s: tuple[float, float], faults: tuple[PhaseOverride, ...]
) -> None:
    """No speed is no result: never "ruled out", never "no significant vibration"."""
    phases = (*_sweep(*faults), _phase("cruise", 13.0, 70.0, 70.0, *faults))
    result = run_sim_pipeline(
        tmp_path,
        car=DEFAULT_CAR,
        sensors=SENSORS,
        scenario_name="mostly-no-speed",
        phases=phases,
        client_seed=CI_SEED,
        fallback_speed_kmh=_FALLBACK_KMH,
        speed_dropout_s=dropout_s,
    )
    try:
        diagnosis = result.diagnosis
        assert diagnosis["verdict"] == "no_fault", diagnosis
        checks = {
            check["source"]: (check["status"], check["reason"])
            for check in diagnosis["source_checks"]
        }
        assert checks["wheel/tire"] == ("not_testable", "speed_missing"), checks
        assert checks["driveline"] == ("not_testable", "speed_missing"), checks
        assert checks["brakes"] == ("not_testable", "speed_missing"), checks
        # The car has a top-gear ratio: the engine RPM would have come from the speed.
        assert checks["engine"] == ("not_testable", "speed_missing"), checks
        assert not {status for status, _ in checks.values()} & {
            "candidate",
            "ruled_out",
            "ruled_out_estimated",
        }, checks
        owner = result.report.owner
        assert owner.headline == "No result: this run could not check for a cause"
        assert "GPS" in owner.next_step, owner.next_step
        engine_gap = next(gap for gap in owner.not_covered if gap.startswith("Engine:"))
        assert "the live speed (GPS or OBD-II) was missing" in engine_gap, engine_gap
        assert "top-gear ratio" not in engine_gap, engine_gap
        assert owner.covered is not None and "unknown" not in owner.covered, owner.covered
        if dropout_s == (0.0, 100.0):
            assert owner.covered.startswith(
                "No live speed was recorded, so the speeds and driving phases are not known;"
                " sensors at "
            ), owner.covered
        shop = " ".join(result.report.mechanic.shop)
        assert shop.endswith("neither indicates nor rules out a repair."), shop
    finally:
        result.history_db.close()


def test_a_long_speed_dropout_is_listed_as_not_covered(tmp_path: Path) -> None:
    """The checks a run with a dropout makes hold for the part with speed only."""
    phases = (*_sweep(), _phase("cruise", 13.0, 70.0, 70.0))
    result = run_sim_pipeline(
        tmp_path,
        car=DEFAULT_CAR,
        sensors=SENSORS,
        scenario_name="long-speed-dropout",
        phases=phases,
        client_seed=CI_SEED,
        fallback_speed_kmh=_FALLBACK_KMH,
        speed_dropout_s=(14.0, 28.0),
    )
    try:
        assert result.diagnosis["verdict"] == "no_fault", result.diagnosis
        not_covered = " ".join(result.report.owner.not_covered)
        assert re.search(
            r"The 1[34] s without GPS speed: any vibration there was not compared", not_covered
        ), not_covered
    finally:
        result.history_db.close()
