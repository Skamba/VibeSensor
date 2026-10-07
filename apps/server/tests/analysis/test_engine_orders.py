"""The engine orders the analysis tests follow the car's engine profile.

A tone at an engine's firing order is that engine's order (E1.5 for an
inline-3, E3 for a six, E4 for a V8); without a profile only E1 and E2 are
tested. Where an engine order sits on a road-speed order and the RPM is only
estimated from the speed, the two are not told apart: the diagnosis names both
and is never Strong.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_support.analysis import run_analysis
from test_support.core import FINAL_DRIVE, GEAR_RATIO, standard_metadata, wheel_hz
from test_support.synthetic_samples import make_sample

from vibesensor.analysis._reference_resolution import ESTIMATED_RPM_SOURCE
from vibesensor.domain.engine_profile import EngineProfile

_SENSORS = ("front_left_wheel", "front_right_wheel", "driver_seat", "trunk")
# A final drive and top gear that put no engine order of these engines on a
# wheel or propshaft order (E1 2.24, E1.5 3.36, E3 6.72, E4 8.96 per wheel turn
# against T2 2, P1 2.8, P2 5.6).
_APART_FINAL_DRIVE = 2.8
_APART_TOP_GEAR = 0.8


def _engine_drive(
    multiple: float,
    *,
    final_drive: float,
    top_gear: float,
    measured_rpm: bool = False,
    gains: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """A tone at *multiple* x crank speed, swept 50-115 km/h in top gear, *gains* louder
    at some sensors."""
    samples = []
    for step in range(60):
        speed_kmh = 50.0 + 65.0 * step / 59
        crank_hz = wheel_hz(speed_kmh) * final_drive * top_gear
        for index, location in enumerate(_SENSORS):
            jitter = 1.0 + 0.03 * ((step * 7 + index) % 5)
            sample = make_sample(
                t_s=step * 0.5,
                speed_kmh=speed_kmh,
                client_name=location,
                location=location,
                top_peaks=[
                    {
                        "hz": multiple * crank_hz,
                        "amp": 0.06 * jitter * (gains or {}).get(location, 1.0),
                    },
                    {"hz": 142.5, "amp": 0.004},
                ],
                vibration_strength_db=28.0,
                strength_floor_amp_g=0.004,
                engine_rpm=crank_hz * 60.0,
            )
            sample["engine_rpm_source"] = "obd2" if measured_rpm else ESTIMATED_RPM_SOURCE
            samples.append(sample)
    return samples


def _propshaft_upshifts(
    final_drive: float, gears: tuple[tuple[float, int], ...]
) -> list[dict[str, Any]]:
    """A propshaft tone at twice shaft speed (P2) on a pull through *gears*
    ``(ratio, half-second steps)``, 30 to 115 km/h, with OBD-II RPM."""
    samples = []
    total = sum(steps for _gear, steps in gears)
    index = 0
    for gear, steps in gears:
        for _step in range(steps):
            speed_kmh = 30.0 + 85.0 * index / (total - 1)
            shaft_hz = wheel_hz(speed_kmh) * final_drive
            for sensor, location in enumerate(_SENSORS):
                jitter = 1.0 + 0.03 * ((index * 7 + sensor) % 5)
                sample = make_sample(
                    t_s=index * 0.5,
                    speed_kmh=speed_kmh,
                    client_name=location,
                    location=location,
                    top_peaks=[
                        {"hz": 2.0 * shaft_hz, "amp": 0.06 * jitter},
                        {"hz": 142.5, "amp": 0.004},
                    ],
                    vibration_strength_db=28.0,
                    strength_floor_amp_g=0.004,
                    engine_rpm=shaft_hz * gear * 60.0,
                )
                sample["engine_rpm_source"] = "obd2"
                samples.append(sample)
            index += 1
    return samples


def _diagnose(
    samples: list[dict[str, Any]],
    profile: EngineProfile | None,
    *,
    final_drive: float,
    top_gear: float,
) -> dict[str, Any]:
    car: dict[str, Any] = {"id": "car-1", "name": "Test car", "fuel_type": "ICE"}
    if profile is not None:
        car["engine_profile"] = {"layout": profile.layout, "cylinders": profile.cylinders}
    metadata = standard_metadata(
        run_id="run-1",
        final_drive_ratio=final_drive,
        current_gear_ratio=top_gear,
        active_car_snapshot=car,
    )
    return run_analysis(samples, metadata)["diagnosis"]


@pytest.mark.parametrize(
    ("profile", "multiple", "order_code"),
    [
        pytest.param(EngineProfile("inline", 3), 1.5, "E1.5", id="inline-3-fires-at-e1.5"),
        pytest.param(EngineProfile("inline", 4), 2.0, "E2", id="inline-4-fires-at-e2"),
        pytest.param(EngineProfile("inline", 6), 3.0, "E3", id="inline-6-fires-at-e3"),
        pytest.param(EngineProfile("v", 8), 4.0, "E4", id="v8-fires-at-e4"),
    ],
)
def test_a_tone_at_the_firing_order_is_the_engine(
    profile: EngineProfile, multiple: float, order_code: str
) -> None:
    diagnosis = _diagnose(
        _engine_drive(multiple, final_drive=_APART_FINAL_DRIVE, top_gear=_APART_TOP_GEAR),
        profile,
        final_drive=_APART_FINAL_DRIVE,
        top_gear=_APART_TOP_GEAR,
    )

    assert (diagnosis["source"], diagnosis["order_code"]) == ("engine", order_code)
    assert "alternative" not in diagnosis
    assert diagnosis["conditions"]["engine_profile"] == {
        "layout": profile.layout,
        "cylinders": profile.cylinders,
    }
    assert [row["code"] for row in diagnosis["conditions"]["engine_orders"]] == [
        order.code for order in profile.orders
    ]


def test_without_a_profile_only_e1_and_e2_are_tested() -> None:
    diagnosis = _diagnose(
        _engine_drive(3.0, final_drive=_APART_FINAL_DRIVE, top_gear=_APART_TOP_GEAR),
        None,
        final_drive=_APART_FINAL_DRIVE,
        top_gear=_APART_TOP_GEAR,
    )

    assert diagnosis["order_code"] not in {"E3", "E1", "E2"}
    assert diagnosis["conditions"]["engine_profile"] is None
    assert [row["code"] for row in diagnosis["conditions"]["engine_orders"]] == ["E1", "E2"]


def test_the_spectrum_marks_the_profiles_engine_orders() -> None:
    diagnosis = _diagnose(
        _engine_drive(3.0, final_drive=_APART_FINAL_DRIVE, top_gear=_APART_TOP_GEAR),
        EngineProfile("inline", 6),
        final_drive=_APART_FINAL_DRIVE,
        top_gear=_APART_TOP_GEAR,
    )

    markers = diagnosis["spectrum"]["order_markers"]
    assert {"E1", "E3"} <= set(markers)
    assert "E2" not in markers
    assert markers["E3"] == pytest.approx(3.0 * markers["E1"])


# On the test car's own ratios (final drive 3.08, top gear 0.64) a six's E3
# turns 5.91 times per wheel turn, the propshaft's P2 6.16 times.
def test_an_engine_order_on_a_propshaft_order_names_both_without_measured_rpm() -> None:
    diagnosis = _diagnose(
        _engine_drive(3.0, final_drive=FINAL_DRIVE, top_gear=GEAR_RATIO),
        EngineProfile("inline", 6),
        final_drive=FINAL_DRIVE,
        top_gear=GEAR_RATIO,
    )

    named = {
        (diagnosis["source"], diagnosis["order_code"]),
        (diagnosis["alternative"]["source"], diagnosis["alternative"]["order_code"]),
    }
    assert named == {("engine", "E3"), ("driveline", "P2")}
    assert diagnosis["verdict"] == "fault"
    assert diagnosis["confidence_level"] != "strong"


def test_with_measured_rpm_an_engine_order_met_in_one_gear_is_the_road_order() -> None:
    # Through 5th to 8th the six's E3 sits on the propshaft's P2 only in 8th
    # (under half the pull): the tone that followed the speed through every
    # gear is the propshaft's, and E3 is not a second finding.
    diagnosis = _diagnose(
        _propshaft_upshifts(FINAL_DRIVE, ((1.32, 15), (1.0, 15), (0.84, 15), (GEAR_RATIO, 40))),
        EngineProfile("inline", 6),
        final_drive=FINAL_DRIVE,
        top_gear=GEAR_RATIO,
    )

    assert (diagnosis["source"], diagnosis["order_code"]) == ("driveline", "P2")
    assert "alternative" not in diagnosis
    assert "E3" not in {row["order_code"] for row in diagnosis["order_findings"]}


@pytest.mark.parametrize(
    ("gains", "named"),
    [
        pytest.param(
            {"front_left_wheel": 2.0, "front_right_wheel": 2.0},
            [("engine", "E3"), ("driveline", "P2")],
            id="felt-at-the-front-engine-first",
        ),
        pytest.param(
            {"trunk": 3.0}, [("driveline", "P2"), ("engine", "E3")], id="felt-at-the-rear"
        ),
    ],
)
def test_the_pair_is_named_from_where_the_shake_is_strongest(
    gains: dict[str, float], named: list[tuple[str, str]]
) -> None:
    diagnosis = _diagnose(
        _engine_drive(3.0, final_drive=FINAL_DRIVE, top_gear=GEAR_RATIO, gains=gains),
        EngineProfile("inline", 6),
        final_drive=FINAL_DRIVE,
        top_gear=GEAR_RATIO,
    )

    assert [
        (diagnosis["source"], diagnosis["order_code"]),
        (diagnosis["alternative"]["source"], diagnosis["alternative"]["order_code"]),
    ] == named
