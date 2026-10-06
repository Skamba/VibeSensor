"""The car's drive layout decides which driveline parts the advice names.

The driveline order turns at wheel speed x final drive. A front-wheel-drive car
has no propshaft: only its gearbox output shaft, final-drive pinion and
differential bearings turn at that speed (the drive shafts and CV joints turn at
wheel speed, so their faults show at the wheel order), and a P1/P2 shake points
there. A rear-wheel-drive car keeps the propshaft advice; an all-wheel-drive car
gets both propshafts, the axle the sensors point to first. Without a layout the
advice stays the propshaft one and the report says the layout was not given.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_support.analysis import run_analysis
from test_support.core import (
    ALL_WHEEL_SENSORS,
    FINAL_DRIVE,
    engine_hz,
    standard_metadata,
    wheel_hz,
)
from test_support.report_rendering import (
    propshaft_mentions,
    report_view_for,
    report_view_texts,
    wheel_speed_part_mentions,
)
from test_support.synthetic_samples import make_noise_samples, make_sample

from vibesensor.report.view_model import ReportView

_RWD_P1_STEP = (
    "Have the propshaft checked for runout and balance, and the joints (U-joints or flex discs)"
    " for play."
)


def _p1_samples(*, front: float, rear: float, n: int = 40, order: int = 1) -> list[dict[str, Any]]:
    """A once- (or ``order``-) per-driveshaft-turn shake over a 50-108 km/h sweep."""
    samples = []
    for i in range(n):
        speed = 50.0 + i * 1.5
        for sensor in ALL_WHEEL_SENSORS:
            amp = front if sensor.startswith("front") else rear
            samples.append(
                make_sample(
                    t_s=float(i),
                    speed_kmh=speed,
                    client_name=sensor,
                    top_peaks=[
                        {"hz": order * wheel_hz(speed) * FINAL_DRIVE, "amp": amp},
                        {"hz": 200.0, "amp": 0.004},
                    ],
                    vibration_strength_db=24.0 if amp > 0.03 else 16.0,
                    strength_floor_amp_g=0.004,
                    engine_rpm=engine_hz(speed) * 60.0,
                )
            )
    return _gps(samples)


def _gps(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for sample in samples:
        sample.update(speed_source="gps", engine_rpm_source="estimated_from_speed_and_ratios")
    return samples


def _car(**snapshot: Any) -> dict[str, Any]:
    return standard_metadata(
        car_name="Test car", active_car_snapshot={"fuel_type": "ICE", **snapshot}
    )


def _conditions(view: ReportView) -> dict[str, str]:
    return {fact.label: fact.value for fact in view.mechanic.conditions}


def test_a_fwd_car_is_never_told_to_check_a_propshaft() -> None:
    summary = run_analysis(_p1_samples(front=0.05, rear=0.015), _car(drive_layout="FWD"))
    diagnosis = summary["diagnosis"]
    view = report_view_for(summary)
    view_nl = report_view_for(summary, lang="nl")

    assert (diagnosis["source"], diagnosis["order_code"], diagnosis["zone"]) == (
        "driveline",
        "P1",
        "front_axle",
    )
    assert diagnosis["driveline_parts"] == ["front_drive"]
    conditions = diagnosis["conditions"]
    assert (conditions["drive_layout"], conditions["propshaft"]) == ("FWD", False)
    assert conditions["final_drive_axle"] == "front"
    for texts in (report_view_texts(view), report_view_texts(view_nl)):
        assert propshaft_mentions(texts) == []
        assert wheel_speed_part_mentions(texts) == []
    for part in ("gearbox output shaft", "final-drive pinion", "differential bearings"):
        assert part in view.owner.next_step
        assert part in view.owner.headline
    assert "pignon van de eindoverbrenging" in view_nl.owner.next_step
    assert any("final-drive pinion" in line for line in view.mechanic.shop)
    assert view.mechanic.worksheet[0].order == "P1 - once per gearbox output-shaft turn"
    assert _conditions(view)["Drive layout"].startswith("front-wheel drive")
    assert "front axle" in _conditions(view)["Final drive"]
    assert _conditions(view_nl)["Aangedreven wielen"].startswith("voorwielaandrijving")


def test_a_fwd_driveline_shake_no_axle_dominates_points_at_the_driven_axle() -> None:
    """With no axle standing out, the driven axle is where to look, not a centre tunnel."""
    summary = run_analysis(_p1_samples(front=0.03, rear=0.03), _car(drive_layout="FWD"))

    assert summary["diagnosis"]["zone"] == "front_axle"
    assert "near the front axle" in report_view_for(summary).owner.headline


def test_a_rwd_car_keeps_the_propshaft_advice_and_adds_the_rear_differential() -> None:
    summary = run_analysis(_p1_samples(front=0.015, rear=0.05), _car(drive_layout="RWD"))
    diagnosis = summary["diagnosis"]
    view = report_view_for(summary)

    assert diagnosis["zone"] == "rear_axle"
    assert diagnosis["driveline_parts"] == ["propshaft_rear"]
    assert view.owner.next_step == _RWD_P1_STEP
    assert "propshaft or its joints" in view.owner.headline
    assert any("rear differential" in line for line in view.mechanic.shop)
    assert _conditions(view)["Drive layout"].startswith("rear-wheel drive")


def test_a_fwd_twice_per_turn_shake_is_not_blamed_on_cv_joint_angles() -> None:
    """P2 turns with the gearbox output too: CV joint working angles do not make it."""
    summary = run_analysis(_p1_samples(front=0.05, rear=0.015, order=2), _car(drive_layout="FWD"))
    view = report_view_for(summary)

    assert (summary["diagnosis"]["source"], summary["diagnosis"]["order_code"]) == (
        "driveline",
        "P2",
    )
    assert "gearbox output shaft" in view.owner.next_step
    for lang in ("en", "nl"):
        texts = report_view_texts(report_view_for(summary, lang=lang))
        assert wheel_speed_part_mentions(texts) == []
        assert not [text for text in texts if "working angle" in text or "werkhoek" in text]


@pytest.mark.parametrize(
    ("front", "rear", "parts", "first_checked"),
    [
        pytest.param(0.05, 0.015, ["front_drive", "propshaft_rear"], "front propshaft", id="front"),
        pytest.param(0.015, 0.05, ["propshaft_rear", "front_drive"], "propshaft", id="rear"),
    ],
)
def test_an_awd_car_names_the_axle_the_sensors_point_to_first(
    front: float, rear: float, parts: list[str], first_checked: str
) -> None:
    """A longitudinal AWD car (xDrive, quattro) drives its front differential by a propshaft."""
    summary = run_analysis(_p1_samples(front=front, rear=rear), _car(drive_layout="AWD"))
    view = report_view_for(summary)

    assert summary["diagnosis"]["driveline_parts"] == parts
    assert view.owner.next_step.startswith(f"Have the {first_checked}"), view.owner.next_step
    # Both axles stay in the advice: the shop checks the other one too.
    shop = " ".join(view.mechanic.shop)
    assert "front propshaft" in shop and "front differential" in shop
    assert "propshaft to the rear axle" in view.owner.next_step
    for lang in ("en", "nl"):
        texts = report_view_texts(report_view_for(summary, lang=lang))
        assert wheel_speed_part_mentions(texts) == []


def test_without_a_drive_layout_the_propshaft_advice_stays_and_the_report_says_so() -> None:
    summary = run_analysis(_p1_samples(front=0.05, rear=0.015), _car())
    diagnosis = summary["diagnosis"]
    view = report_view_for(summary)
    view_nl = report_view_for(summary, lang="nl")

    assert diagnosis["driveline_parts"] == []
    assert diagnosis["conditions"]["drive_layout"] is None
    assert view.owner.next_step.startswith(_RWD_P1_STEP)
    assert "drive layout was not given" in view.owner.next_step
    assert "gearbox output shaft, the final-drive pinion" in view.owner.next_step
    assert "aandrijving" not in view_nl.owner.next_step.lower()[:20]
    assert "pignon van de eindoverbrenging" in view_nl.owner.next_step
    assert wheel_speed_part_mentions([view.owner.next_step, view_nl.owner.next_step]) == []
    assert _conditions(view)["Drive layout"].startswith("not provided")
    assert _conditions(view_nl)["Aangedreven wielen"].startswith("niet opgegeven")


def test_a_healthy_fwd_drive_rules_the_driveline_out_without_a_propshaft() -> None:
    summary = run_analysis(
        _gps(make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30)),
        _car(drive_layout="FWD"),
    )
    view = report_view_for(summary)

    assert summary["diagnosis"]["verdict"] == "no_fault"
    assert "Driveline: no driveline-order vibration found" in view.mechanic.ruled_out
    for texts in (report_view_texts(view), report_view_texts(report_view_for(summary, lang="nl"))):
        assert propshaft_mentions(texts) == []
        assert wheel_speed_part_mentions(texts) == []


def test_an_ev_keeps_its_motor_advice_whatever_its_layout() -> None:
    """An EV has no propshaft either way: its motor is the driveline order."""
    for snapshot in ({"fuel_type": "EV"}, {"fuel_type": "EV", "drive_layout": "RWD"}):
        summary = run_analysis(
            _p1_samples(front=0.015, rear=0.05),
            standard_metadata(
                car_name="Test car", active_car_snapshot=snapshot, current_gear_ratio=None
            ),
        )
        view = report_view_for(summary)

        assert summary["diagnosis"]["driveline_parts"] == []
        assert view.owner.next_step.startswith("Have the drive unit checked")
        assert "drive layout" not in view.owner.next_step
