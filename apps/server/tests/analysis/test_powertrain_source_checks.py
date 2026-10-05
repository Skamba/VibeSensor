"""EVs and plug-in hybrids: the checks follow the car's powertrain (docs/user_journeys.md §5.3).

An EV has no engine: the engine check is "not applicable", its motor (which turns
at wheel speed x reduction ratio, the driveshaft order) is what the report calls
the motor, and no neutral coast-down can be judged. A plug-in hybrid's engine may
be off: without OBD-II the engine check is hedged, and with OBD-II only the time
the engine ran counts.
"""

from __future__ import annotations

from typing import Any

from test_support.analysis import run_analysis
from test_support.core import ALL_WHEEL_SENSORS, FINAL_DRIVE, standard_metadata, wheel_hz
from test_support.report_rendering import report_view_for
from test_support.synthetic_samples import make_engine_order_samples, make_noise_samples


def _car(fuel_type: str, **overrides: Any) -> dict[str, Any]:
    if fuel_type == "EV":
        # An EV car keeps no top gear: its single reduction ratio is the final drive.
        overrides["current_gear_ratio"] = None
    return standard_metadata(
        car_name="Test car", active_car_snapshot={"fuel_type": fuel_type}, **overrides
    )


def _checks(summary: dict[str, Any]) -> dict[str, tuple[str, str | None]]:
    return {
        check["source"]: (check["status"], check["reason"])
        for check in summary["diagnosis"]["source_checks"]
    }


def _gps(samples: list[dict[str, Any]], *, rpm: float | None = None) -> list[dict[str, Any]]:
    for sample in samples:
        sample["speed_source"] = "gps"
        if rpm is None:
            sample.update(engine_rpm=2100.0, engine_rpm_source="estimated_from_speed_and_ratios")
        else:
            sample.update(engine_rpm=rpm, engine_rpm_source="obd2")
    return samples


def test_an_ev_has_no_engine_check_and_its_motor_is_the_driveline_order() -> None:
    summary = run_analysis(
        _gps(make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30)),
        _car("EV"),
    )
    view = report_view_for(summary)
    conditions = {fact.label: fact.value for fact in view.mechanic.conditions}

    assert _checks(summary)["engine"] == ("not_applicable", "electric_car")
    assert view.mechanic.ruled_out[1:] == (
        "Electric motor: no vibration found at once or twice per motor revolution",
        "Combustion engine: not applicable: an electric car has no combustion engine",
        # Brake judder needs firm braking from speed, which this drive never did.
        "Brakes: not testable: the drive did not brake firmly from speed",
    )
    assert (
        view.mechanic.worksheet_empty == "No vibration that follows wheel or motor speed was found."
    )
    assert view.owner.description == (
        "Nothing stood out in the checks this run could make: wheels/tires and electric motor."
        " Not checked, so not shown to be fine: brakes."
    )
    # The motor check needs no top gear: the motor turns at wheel speed x reduction ratio.
    assert conditions["Powertrain"].startswith("electric (EV): the motor is checked at once")
    assert "(wheel speed × reduction ratio)" in conditions["Powertrain"]
    assert _checks(summary)["driveline"] == ("ruled_out", "no_matching_order")
    assert "electrical and gear-mesh orders are not analysed" in conditions["Powertrain"]
    assert f"{FINAL_DRIVE:.2f}" in conditions["Reduction ratio (final drive)"]
    assert "Top gear ratio" not in conditions
    assert "Engine RPM" not in conditions


def test_an_evs_speed_check_names_its_motor_not_a_drivetrain() -> None:
    summary = run_analysis(
        _gps(make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30)),
        _car("EV"),
    )

    for lang, label, motor, combustion in (
        ("en", "Speed variation", "electric-motor orders", "drivetrain"),
        ("nl", "Snelheidsvariatie", "elektromotor", "aandrijving"),
    ):
        (check,) = (
            check
            for check in report_view_for(summary, lang=lang).quality.checks
            if check.label == label
        )
        assert motor in check.detail
        assert combustion not in check.detail


def test_an_ev_motor_vibration_is_named_the_motor_not_the_engine() -> None:
    motor_hz = wheel_hz(80.0) * FINAL_DRIVE
    samples = _gps(
        make_engine_order_samples(
            sensors=ALL_WHEEL_SENSORS, n_samples=40, _engine_hz_override=motor_hz
        )
    )
    guided = [{"phase": "coast_down", "start_t_s": 28.0, "end_t_s": 40.0}]
    summary = run_analysis(samples, _car("EV", guided_phases=guided))
    diagnosis = summary["diagnosis"]
    view = report_view_for(summary)
    view_nl = report_view_for(summary, lang="nl")

    assert (diagnosis["source"], diagnosis["order_code"]) == ("driveline", "P1")
    # No neutral decouples the motor, so the coast-down judges nothing.
    assert diagnosis["speed_dependence"] is None
    assert "E1" not in (diagnosis["spectrum"] or {}).get("order_markers", {})
    assert "the electric motor or its reduction gear" in view.owner.headline
    assert view.owner.description.startswith("A shake that repeats once per motor revolution")
    assert view.owner.next_step.startswith("Have the drive unit checked")
    assert "elektromotor" in view_nl.owner.headline
    for text in (view.owner.headline, view.owner.description, *view.mechanic.shop):
        assert "engine" not in text.lower()
        assert "propshaft" not in text.lower()


def test_a_plug_in_hybrid_without_obd_hedges_the_engine_check() -> None:
    summary = run_analysis(
        _gps(make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30)), _car("PHEV")
    )
    view = report_view_for(summary)
    conditions = {fact.label: fact.value for fact in view.mechanic.conditions}

    assert _checks(summary)["engine"] == ("ruled_out_estimated", "engine_may_be_off")
    assert view.mechanic.ruled_out[2] == (
        "Engine: no match with the engine orders estimated for top gear, but a plug-in"
        " hybrid's engine may have been off; not conclusive"
    )
    assert conditions["Powertrain"].endswith(
        "without OBD-II RPM the engine check is not conclusive"
    )
    assert view.owner.not_covered[0].startswith(
        "Engine: a plug-in hybrid's engine may have been off"
    )


def test_obd_rpm_showing_the_engine_off_leaves_the_engine_untested() -> None:
    """A hybrid that drove electrically: a measured 0 rpm is no reason to estimate engine orders."""
    summary = run_analysis(
        _gps(make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30), rpm=0.0), _car("PHEV")
    )
    view = report_view_for(summary)

    assert summary["diagnosis"]["conditions"]["rpm_source"] == "measured"
    assert _checks(summary)["engine"] == ("not_testable", "engine_not_running")
    assert view.mechanic.ruled_out[2] == (
        "Engine: not testable: OBD-II RPM shows the engine was off for most of the drive"
    )
    assert view.owner.description.endswith(
        "Not checked, so not shown to be fine: engine and brakes."
    )


def test_obd_rpm_showing_the_engine_running_checks_a_hybrid_engine() -> None:
    summary = run_analysis(
        _gps(make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30), rpm=2100.0),
        _car("PHEV"),
    )
    conditions = {fact.label: fact.value for fact in report_view_for(summary).mechanic.conditions}

    assert _checks(summary)["engine"] == ("ruled_out", "no_matching_order")
    assert "checked only while OBD-II RPM showed it running" in conditions["Powertrain"]


def test_the_report_says_when_the_powertrain_is_not_known() -> None:
    summary = run_analysis(_gps(make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30)))
    conditions = {fact.label: fact.value for fact in report_view_for(summary).mechanic.conditions}
    conditions_nl = {
        fact.label: fact.value for fact in report_view_for(summary, lang="nl").mechanic.conditions
    }

    assert conditions["Powertrain"] == "not provided; analysed as a car with a combustion engine"
    assert conditions_nl["Aandrijving"].startswith("niet opgegeven")


def test_obd_reading_0_rpm_while_driving_a_combustion_car_is_not_an_engine_off() -> None:
    """A combustion engine does not stop while the car drives: 0 rpm is a bad reading.

    The engine orders fall back to RPM estimated from speed in top gear, as with
    no RPM at all, and the report never words it as a hybrid driving electrically.
    """
    for car in (_car("ICE"), None):
        engine = _gps(make_engine_order_samples(sensors=ALL_WHEEL_SENSORS, n_samples=40), rpm=0.0)
        summary = run_analysis(engine, car)
        noise = run_analysis(
            _gps(make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30), rpm=0.0), car
        )
        view = report_view_for(noise)
        texts = [*view.mechanic.ruled_out, *view.owner.not_covered, view.owner.description]
        texts += [fact.value for fact in view.mechanic.conditions]

        assert summary["diagnosis"]["source"] == "engine"
        assert noise["diagnosis"]["conditions"]["rpm_source"] == "estimated_top_gear"
        assert _checks(noise)["engine"] == ("ruled_out_estimated", "top_gear_assumed")
        for text in texts:
            assert "hybrid" not in text.lower() and "engine was off" not in text.lower(), text
