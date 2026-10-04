"""Source checks claim only what was tested: estimates are hedged, a typed-in speed tests nothing.

A "ruled out" must not rest on a weak car-library ratio, on engine RPM estimated
for top gear, or on a speed the user typed in (every sample then carries that
one value, even on a desk). The test conditions say where each reference came from,
and the report's speed check passes only for a live speed that varied.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_support.analysis import run_analysis
from test_support.core import ALL_WHEEL_SENSORS, standard_metadata
from test_support.report_rendering import report_view_for
from test_support.synthetic_samples import (
    make_engine_order_samples,
    make_fault_samples,
    make_noise_samples,
)

from vibesensor.recording.run_suitability_codec import (
    run_suitability_from_payload,
    run_suitability_payload,
)


def _driven(
    samples: list[dict[str, Any]], *, speed_source: str = "gps", rpm: str | None = "estimated"
) -> list[dict[str, Any]]:
    """Stamp samples as the recorder does: the speed source and the engine RPM source."""
    for sample in samples:
        sample["speed_source"] = speed_source
        if rpm == "estimated":
            sample.update(engine_rpm=2100.0, engine_rpm_source="estimated_from_speed_and_ratios")
        elif rpm == "obd":
            sample.update(engine_rpm=2100.0, engine_rpm_source="obd2")
    return samples


def _library_car(final_drive: str, top_gear: str, **car: Any) -> dict[str, Any]:
    return standard_metadata(
        car_name="Library car",
        active_car_snapshot={
            "order_reference_status": {
                "selection_source_status": "exact_row",
                "tire_dimensions_confidence": "official_exact",
                "final_drive_ratio_confidence": final_drive,
                "current_gear_ratio_confidence": top_gear,
            },
            **car,
        },
    )


def _checks(summary: dict[str, Any]) -> dict[str, tuple[str, str | None]]:
    return {
        check["source"]: (check["status"], check["reason"])
        for check in summary["diagnosis"]["source_checks"]
    }


@pytest.mark.parametrize(
    ("final_drive", "top_gear", "driveline", "engine"),
    [
        # Checked ratios: the driveline is ruled out, the engine only for top gear.
        (
            "official_exact",
            "reputable_secondary_crosschecked",
            ("ruled_out", "no_matching_order"),
            ("ruled_out_estimated", "top_gear_assumed"),
        ),
        # A model-family final drive hedges both orders it places.
        (
            "family_default",
            "official_exact",
            ("ruled_out_estimated", "estimated_final_drive"),
            ("ruled_out_estimated", "estimated_final_drive"),
        ),
        (
            "official_derived",
            "unverified",
            ("ruled_out", "no_matching_order"),
            ("ruled_out_estimated", "estimated_top_gear"),
        ),
    ],
)
def test_a_no_match_resting_on_an_estimate_is_hedged(
    final_drive: str,
    top_gear: str,
    driveline: tuple[str, str],
    engine: tuple[str, str],
) -> None:
    samples = _driven(make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30))
    summary = run_analysis(samples, _library_car(final_drive, top_gear, fuel_type="ICE"))
    checks = _checks(summary)
    conditions = summary["diagnosis"]["conditions"]

    assert summary["diagnosis"]["verdict"] == "no_fault"
    assert checks == {
        "wheel/tire": ("ruled_out", "no_matching_order"),
        "driveline": driveline,
        "engine": engine,
    }
    assert conditions["rpm_source"] == "estimated_top_gear"
    assert (
        conditions["tire_provenance"],
        conditions["final_drive_provenance"],
        conditions["gear_ratio_provenance"],
        conditions["fuel_type"],
    ) == ("official_exact", final_drive, top_gear, "ICE")


def test_report_names_the_estimate_behind_each_hedged_line() -> None:
    samples = _driven(make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30))
    summary = run_analysis(samples, _library_car("family_default", "official_exact"))

    ruled_out = report_view_for(summary).mechanic.ruled_out
    ruled_out_nl = report_view_for(summary, lang="nl").mechanic.ruled_out

    assert ruled_out == (
        "Wheels/tires: no once- or twice-per-wheel-turn vibration found",
        "Driveline: no match with the estimated final drive (car-library estimate); not conclusive",
        "Engine: no match with the estimated final drive (car-library estimate); not conclusive",
    )
    assert "niet doorslaggevend" in ruled_out_nl[1]


def test_report_prints_each_library_ratio_with_its_provenance_and_hedges_page_one() -> None:
    samples = _driven(make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30))
    view = report_view_for(run_analysis(samples, _library_car("family_default", "official_exact")))
    conditions = {fact.label: fact.value for fact in view.mechanic.conditions}

    assert conditions["Tire size"].endswith("(car library, official)")
    assert conditions["Final drive"] == "3.08 (car library, model-family estimate)"
    assert conditions["Top gear ratio"] == "0.64 (car library, official)"
    assert conditions["Engine RPM"] == "not measured; estimated from speed assuming top gear"
    assert view.owner.description == (
        "Nothing stood out in the checks this run could make: wheels/tires,"
        " driveline (against an estimated final drive) and engine (against an"
        " estimated final drive, top gear only)."
    )
    assert view.owner.not_covered[1].startswith(
        "Engine: checked only against a car-library estimate of the final drive, in top gear"
    )


def test_measured_rpm_rules_the_engine_out_whatever_the_library_ratios() -> None:
    samples = _driven(make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30), rpm="obd")
    summary = run_analysis(samples, _library_car("unverified", "family_default"))

    assert _checks(summary)["engine"] == ("ruled_out", "no_matching_order")
    assert summary["diagnosis"]["conditions"]["rpm_source"] == "measured"


def test_references_without_recorded_confidence_are_the_users_own_or_missing() -> None:
    samples = _driven(make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30))
    conditions = run_analysis(samples, standard_metadata(current_gear_ratio=None))["diagnosis"][
        "conditions"
    ]

    assert (
        conditions["tire_provenance"],
        conditions["final_drive_provenance"],
        conditions["gear_ratio_provenance"],
    ) == ("user_confirmed", "user_confirmed", "missing")


@pytest.mark.parametrize("speed_source", ["manual", "fallback_manual"])
def test_a_typed_in_speed_rules_nothing_out(speed_source: str) -> None:
    """The desk run: sensors still, speed set to 50 km/h by hand, no fault anywhere."""
    samples = _driven(
        make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30), speed_source=speed_source
    )
    summary = run_analysis(samples)
    ruled_out = report_view_for(summary).mechanic.ruled_out

    assert summary["diagnosis"]["verdict"] == "no_fault"
    assert set(_checks(summary).values()) == {("not_testable", "manual_speed")}
    assert ruled_out[0] == (
        "Wheels/tires: not testable: the speed was entered by hand, so order matching only"
        " holds at exactly that speed"
    )


def test_a_typed_in_speed_still_names_a_found_cause_but_says_why_it_is_hedged() -> None:
    samples = _driven(
        make_fault_samples(fault_sensor="front-left", sensors=ALL_WHEEL_SENSORS),
        speed_source="manual",
    )
    diagnosis = run_analysis(samples)["diagnosis"]

    assert (diagnosis["source"], diagnosis["zone"]) == ("wheel/tire", "front_left_wheel")
    assert diagnosis["weak_reasons"][0] == "manual_speed"
    assert _checks({"diagnosis": diagnosis})["driveline"] == ("not_testable", "manual_speed")


_COAST_START_S = 28.0
_GUIDED = [
    {"phase": "sweep", "start_t_s": 0.0, "end_t_s": 14.0},
    {"phase": "hold", "start_t_s": 14.0, "end_t_s": _COAST_START_S},
    {"phase": "coast_down", "start_t_s": _COAST_START_S, "end_t_s": 40.0},
]


def test_a_typed_in_speed_cannot_judge_the_neutral_coast_down() -> None:
    """A typed-in speed does not fall while coasting, so the coast-down rules nothing out."""
    samples = _driven(
        make_engine_order_samples(sensors=ALL_WHEEL_SENSORS, n_samples=40),
        speed_source="manual",
        rpm=None,
    )
    for sample in samples:
        if sample["t_s"] >= _COAST_START_S:
            sample["top_peaks"] = [{"hz": 200.0, "amp": 0.004}]
            sample["vibration_strength_db"] = 8.0
    diagnosis = run_analysis(samples, standard_metadata(guided_phases=_GUIDED))["diagnosis"]

    assert diagnosis["source"] == "engine"
    assert diagnosis["speed_dependence"] is None
    assert _checks({"diagnosis": diagnosis})["wheel/tire"] == ("not_testable", "manual_speed")


def _speed_steps(*speeds_kmh: float) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for step, speed in enumerate(speeds_kmh):
        samples += make_noise_samples(
            sensors=ALL_WHEEL_SENSORS, speed_kmh=speed, n_samples=10, start_t_s=step * 10.0
        )
    return samples


_ORDERS_APART = "The speed could not tell the wheel and drivetrain orders apart."


@pytest.mark.parametrize(
    ("speeds", "speed_source", "detail"),
    [
        pytest.param(
            (50.0,),
            "manual",
            f"{_ORDERS_APART} The speed was entered by hand and does not follow the car;"
            " use GPS or OBD-II speed.",
            id="desk-run-at-a-typed-in-speed",
        ),
        pytest.param(
            (50.0, 70.0, 90.0),
            "manual",
            f"{_ORDERS_APART} The speed was entered by hand and does not follow the car;"
            " use GPS or OBD-II speed.",
            id="typed-in-speed-changed-by-hand",
        ),
        pytest.param(
            (50.0,),
            "gps",
            f"{_ORDERS_APART} The speed stayed almost constant; vary it, for example by slowly"
            " accelerating through the speed range, so the orders separate.",
            id="constant-live-speed",
        ),
        pytest.param(
            (50.0, 70.0, 90.0),
            "gps",
            None,
            id="varied-live-speed",
        ),
    ],
)
def test_the_speed_check_passes_only_for_a_live_speed_that_varied(
    speeds: tuple[float, ...], speed_source: str, detail: str | None
) -> None:
    summary = run_analysis(_driven(_speed_steps(*speeds), speed_source=speed_source))
    (check,) = (
        check
        for check in report_view_for(summary).quality.checks
        if check.label == "Speed variation"
    )
    persisted = summary["run_suitability"]

    assert check.passed is (detail is None)
    assert check.detail == (
        detail or "The speed was usable for matching the wheel and drivetrain orders."
    )
    assert run_suitability_payload(run_suitability_from_payload(persisted)) == persisted


def test_the_speed_check_explains_a_typed_in_speed_in_dutch() -> None:
    summary = run_analysis(_driven(_speed_steps(50.0), speed_source="manual"))
    (check,) = (
        check
        for check in report_view_for(summary, lang="nl").quality.checks
        if check.label == "Snelheidsvariatie"
    )

    assert not check.passed
    assert check.detail.endswith(
        "De snelheid is met de hand ingevoerd en volgt de auto niet; gebruik GPS- of"
        " OBD-II-snelheid."
    )
