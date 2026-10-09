"""Report view model: every page-1/page-2 string for each verdict variant, in en and nl."""

from __future__ import annotations

import re
from copy import deepcopy
from functools import cache
from typing import Any

import pytest
from test_support.analysis import run_analysis
from test_support.core import ALL_WHEEL_SENSORS, standard_metadata
from test_support.report_rendering import report_view_for, report_view_texts
from test_support.synthetic_samples import (
    make_engine_order_samples,
    make_fault_samples,
    make_noise_samples,
)

from vibesensor.recording.run_metadata import run_metadata_from_mapping
from vibesensor.report.view_model import ReportView, build_owner_page, build_report_view
from vibesensor.summary.warning_fields import localize_warning_list

_UNRESOLVED_KEY = re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")
_PERCENT_CONFIDENCE = re.compile(r"\d+\s?%\s*(confidence|zekerheid)", re.IGNORECASE)


@cache
def _wheel_summary() -> dict[str, Any]:
    return run_analysis(make_fault_samples(fault_sensor="front-left", sensors=ALL_WHEEL_SENSORS))


@cache
def _healthy_summary() -> dict[str, Any]:
    # No top-gear ratio and no OBD-II: the engine orders cannot be placed.
    return run_analysis(
        make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30), current_gear_ratio=None
    )


def _variant(**diagnosis: Any) -> dict[str, Any]:
    summary = deepcopy(_wheel_summary())
    summary["diagnosis"].update(diagnosis)
    return summary


def _driveline_summary() -> dict[str, Any]:
    return _variant(
        source="driveline",
        order_code="P1",
        zone="rear_axle",
        confidence_level="moderate",
        frequency_hz=44.1,
        reference_speed_kmh=90.0,
        speed_min_kmh=61.0,
        speed_max_kmh=113.0,
    )


def _engine_summary() -> dict[str, Any]:
    return _variant(
        source="engine",
        order_code="E2",
        zone="engine_bay",
        confidence_level="strong",
        frequency_hz=70.3,
        reference_speed_kmh=90.0,
    )


def _weak_summary() -> dict[str, Any]:
    return _variant(
        verdict="weak_evidence",
        confidence_level="weak",
        zone="front_axle",
        weak_reasons=["spread_across_locations", "narrow_speed_range"],
    )


def _felt_row(source: str, codes: list[str], peak_mg: float, **row: Any) -> dict[str, Any]:
    limits = {"engine": (12.0, 2.0)}.get(source, (25.0, None))
    return {
        "finding_id": "F001",
        "source": source,
        "order_codes": codes,
        "level_mg": 0.267 * peak_mg,
        "peak_mg": peak_mg,
        "share": 1.0 if peak_mg else None,
        "speed_min_kmh": 80.0,
        "speed_max_kmh": 120.0,
        "severity": "workshop" if peak_mg >= limits[0] else ("below_workshop" if peak_mg else None),
        "workshop_mg": limits[0],
        "normal_mg": limits[1],
        **row,
    }


def _felt_summary(reference: str | None, *rows: dict[str, Any], **diagnosis: Any) -> dict[str, Any]:
    fallback = None if reference else "no_cabin_sensor"
    felt = {"reference": reference, "fallback": fallback, "causes": list(rows)}
    return _variant(felt=felt, **diagnosis)


def _felt_trunk_summary() -> dict[str, Any]:
    """The wheels felt in the trunk at a workshop level, with a faint propshaft beside them."""
    return _felt_summary(
        "Trunk",
        _felt_row("wheel/tire", ["T1", "T2"], 60.0, share=0.8),
        _felt_row("driveline", ["P1"], 12.0, share=0.2, finding_id="F002"),
    )


def _felt_engine_normal_summary() -> dict[str, Any]:
    return _felt_summary(
        "Driver Seat",
        _felt_row("engine", ["E2"], 1.5, severity="normal"),
        source="engine",
        order_code="E2",
        zone="engine_bay",
    )


def _guided_summary() -> dict[str, Any]:
    summary = _variant(
        guided_phases=["sweep", "hold", "coast_down", "brake"], speed_dependence="vehicle_speed"
    )
    for check in summary["diagnosis"]["source_checks"]:
        if check["source"] == "engine":
            check.update(status="ruled_out", reason="stayed_in_neutral")
    return summary


def _guided_contradiction_summary() -> dict[str, Any]:
    return _variant(
        verdict="weak_evidence",
        confidence_level="weak",
        guided_phases=["coast_down"],
        speed_dependence="engine_speed",
        weak_reasons=["coast_test_contradicts"],
    )


def _all_text(view: ReportView) -> str:
    owner, mechanic, quality = view.owner, view.mechanic, view.quality
    parts: list[str] = [view.title, *(f"{f.label} {f.value}" for f in view.header)]
    parts += [
        str(value)
        for value in (
            owner.headline,
            owner.level_word,
            owner.level_meaning,
            owner.description,
            owner.candidate,
            owner.covered,
            owner.confirm,
            owner.next_step,
            owner.fallback_step,
            owner.verify,
            owner.felt,
            mechanic.felt_title,
            mechanic.felt_note,
        )
        if value
    ]
    parts += [*owner.reasons, *owner.recapture, *owner.not_covered]
    parts += [f"{f.label} {f.value}" for f in mechanic.conditions]
    parts += [
        " ".join((r.order, r.frequency, r.speeds, r.phases, r.location, r.level))
        for r in mechanic.worksheet
    ]
    parts += [f"{r.location} {r.amplitude} {r.ratio}" for r in mechanic.amplitudes]
    parts += [*mechanic.felt_header]
    parts += [" ".join((r.cause, r.level, r.share, r.judged, r.workshop)) for r in mechanic.felt]
    parts += [*mechanic.ruled_out, *mechanic.shop, mechanic.worksheet_empty or ""]
    parts += [f"{c.label} {c.detail}" for c in quality.checks]
    parts += [*quality.warnings, quality.footer_line]
    return "\n".join(parts)


_SCENARIOS = {
    "healthy": _healthy_summary,
    "wheel": _wheel_summary,
    "driveline": _driveline_summary,
    "engine": _engine_summary,
    "weak": _weak_summary,
    "guided": _guided_summary,
    "guided_contradiction": _guided_contradiction_summary,
    "felt_trunk": _felt_trunk_summary,
    "felt_engine_normal": _felt_engine_normal_summary,
}


@pytest.mark.parametrize("lang", ["en", "nl"])
@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
def test_every_string_is_resolved_and_no_confidence_percentage(scenario: str, lang: str) -> None:
    view = report_view_for(_SCENARIOS[scenario](), lang=lang)
    text = _all_text(view)

    assert not _UNRESOLVED_KEY.findall(text), _UNRESOLVED_KEY.findall(text)
    assert not _PERCENT_CONFIDENCE.search(text)
    assert "None" not in text
    assert "nan" not in text.lower().split()


def test_healthy_run_says_no_significant_vibration_and_what_was_covered() -> None:
    view = report_view_for(_healthy_summary())
    owner = view.owner

    assert owner.verdict == "no_fault"
    assert owner.headline == "No significant vibration found"
    assert owner.level is None and owner.level_word is None
    assert owner.covered is not None and "km/h" in owner.covered
    assert "front-left wheel" in owner.covered
    assert owner.description == (
        "Nothing stood out in the checks this run could make: wheels/tires and driveline."
        " Not checked, so not shown to be fine: engine and brakes."
    )
    assert owner.not_covered[0] == (
        "Engine: no engine RPM — connect an OBD-II adapter,"
        " or add the top-gear ratio to the car (optional)."
    )
    assert owner.verify is None and owner.fallback_step is None
    assert view.mechanic.worksheet == ()
    assert view.mechanic.worksheet_empty == (
        "No vibration that follows wheel, propshaft or engine speed was found."
    )
    assert view.mechanic.shop == ("No repair is indicated by this test.",)
    assert view.owner.diagram.zone is None


@pytest.mark.parametrize(
    ("lang", "covered", "speeds", "driving"),
    [
        (
            "en",
            "No live speed was recorded, so the speeds and driving phases are not known;"
            " sensors at front-left wheel",
            "no live speed recorded",
            "Driving covered",
        ),
        (
            "nl",
            "Er is geen live snelheid vastgelegd, dus de snelheden en rijfasen zijn onbekend;"
            " sensoren bij wiel linksvoor",
            "geen live snelheid vastgelegd",
            "Gereden",
        ),
    ],
)
def test_a_run_without_live_speed_says_so_instead_of_unknown(
    lang: str, covered: str, speeds: str, driving: str
) -> None:
    # GPS chosen but never a fix: no sample has a speed, every second is "speed unknown".
    summary = run_analysis(
        make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30, speed_kmh=None)
    )
    assert summary["phase_info"]["phase_pcts"] == {"speed_unknown": 100.0}
    view = report_view_for(summary, lang=lang)
    header = {fact.label: fact.value for fact in view.header}
    conditions = {fact.label: fact.value for fact in view.mechanic.conditions}
    speeds_label = view.header[3].label

    assert view.owner.covered is not None and view.owner.covered.startswith(covered)
    assert header[speeds_label] == conditions[speeds_label] == speeds
    # Every second would read "unknown speed 100 %": the speeds row already says why.
    assert driving not in conditions, conditions


@pytest.mark.parametrize(
    ("source", "speed_kmh", "lang", "shown"),
    [
        ("gps_unaligned", None, "en", "GPS (no fix during the run)"),
        ("gps_unaligned", None, "nl", "GPS (geen fix tijdens de rit)"),
        ("obd2_unaligned", None, "en", "OBD (no speed received)"),
        ("obd2_unaligned", None, "nl", "OBD (geen snelheid ontvangen)"),
        ("manual", 60.0, "en", "entered by hand"),
        ("manual", 60.0, "nl", "handmatig ingevoerd"),
    ],
)
def test_speed_source_names_the_chosen_source_even_when_it_gave_no_speed(
    source: str, speed_kmh: float | None, lang: str, shown: str
) -> None:
    # A live source that never gave a speed (GPS without a fix, OBD-II without a
    # reading) marks every recorded row "<source>_unaligned", as on the Pi.
    samples = make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30, speed_kmh=speed_kmh)
    for sample in samples:
        sample["speed_source"] = source
    view = report_view_for(run_analysis(samples), lang=lang)
    speed_source_label = {"en": "Speed source", "nl": "Snelheidsbron"}[lang]

    conditions = {fact.label: fact.value for fact in view.mechanic.conditions}
    assert conditions[speed_source_label] == shown


@pytest.mark.parametrize(
    ("lang", "covered"),
    [
        ("en", "50–52\xa0km/h with sensors at front-left wheel"),
        ("nl", "50–52\xa0km/u met sensoren bij wiel linksvoor"),
    ],
)
def test_covered_leaves_out_the_phases_when_no_driving_phase_was_known(
    lang: str, covered: str
) -> None:
    summary = deepcopy(_healthy_summary())
    summary["speed_stats"].update(min_kmh=50.0, max_kmh=52.0)
    summary["phase_info"]["phase_pcts"] = {"speed_unknown": 99.5, "cruise": 0.5}
    owner = report_view_for(summary, lang=lang).owner

    assert owner.covered is not None and owner.covered.startswith(covered), owner.covered


def test_clear_wheel_fault_names_corner_order_level_and_next_steps() -> None:
    summary = _wheel_summary()
    view = report_view_for(summary)
    owner, mechanic = view.owner, view.mechanic
    level = summary["diagnosis"]["confidence_level"]

    assert owner.headline == "Likely cause: a wheel or tire problem at the front-left wheel"
    assert owner.level == level
    assert owner.level_word == level.capitalize()
    assert owner.description.startswith("A shake that repeats once per wheel turn (10.4 Hz")
    assert "stronger at the front-left wheel than at the next sensor" in owner.description
    assert owner.next_step == (
        "Have the front-left wheel balanced and checked for wheel and tire runout."
    )
    assert owner.fallback_step is not None
    assert owner.fallback_step.startswith("If that doesn't fix it: ask the tire shop to road-force")
    assert owner.verify is not None and "T1 60 mg today" in owner.verify
    assert owner.diagram.zone == "front_left_wheel"
    assert owner.diagram.markers[0].strongest

    assert mechanic.worksheet[0].order == "T1 - once per wheel turn"
    assert mechanic.worksheet[0].diagnosed
    assert mechanic.amplitudes[0].location == "front-left wheel"
    assert mechanic.amplitudes[0].amplitude.startswith("60 mg (")
    assert mechanic.amplitudes[0].ratio == "1.0x"
    assert mechanic.amplitude_title == "Amplitude at T1 per location"
    assert mechanic.shop[0].startswith("Balance all four wheels to under 5 g")
    assert mechanic.shop[1].startswith("Road-force all four wheel/tire assemblies")
    assert any(line.startswith("Driveline: ") for line in mechanic.ruled_out)
    assert not any(line.startswith("Wheels/tires") for line in mechanic.ruled_out)


def test_a_sensor_the_order_does_not_reach_reads_not_detected_not_zero_mg() -> None:
    # An order read at its line reads 0 mg at a sensor it does not reach; its dB
    # there only reflects that sensor's floor.
    rows = deepcopy(_wheel_summary()["diagnosis"]["location_amplitudes"])
    for row in rows[1:]:
        row.update(amplitude_mg=0.0, db_above_floor=-26.4, ratio_to_strongest=0.0)
    view = report_view_for(_variant(location_amplitudes=rows))

    assert "measurable only at the front-left wheel" in view.owner.description
    assert [marker.value for marker in view.owner.diagram.markers[1:]] == ["-"] * (len(rows) - 1)
    for amplitude in view.mechanic.amplitudes[1:]:
        assert (amplitude.amplitude, amplitude.ratio) == ("not detected", "-")
    assert view.mechanic.amplitudes[0].ratio == "1.0x"


def test_a_fault_strongest_at_a_loose_sensor_says_so_on_the_owner_page() -> None:
    owner = report_view_for(
        _variant(confidence_level="moderate", weak_reasons=["loose_mount"])
    ).owner

    assert owner.description.endswith(
        "The sensor where it was strongest may be loosely mounted, so how strong it was"
        " there is uncertain."
    )


def _swept_fault_samples(sensors: list[str]) -> list[dict[str, Any]]:
    """A front-left wheel imbalance over a 50-110 km/h sweep."""
    samples: list[dict[str, Any]] = []
    for index, speed in enumerate(range(50, 111, 2)):
        samples += make_fault_samples(
            fault_sensor="front-left",
            sensors=sensors,
            speed_kmh=float(speed),
            n_samples=2,
            start_t_s=index * 2.0,
        )
    return samples


@pytest.mark.parametrize(
    ("sensors", "note"),
    [
        pytest.param(["front-left"], "Only one sensor was used", id="one-sensor"),
        pytest.param(
            ["front-left", "driver-seat"], "Only one wheel had a sensor", id="one-wheel-and-cabin"
        ),
    ],
)
def test_one_wheel_sensor_does_not_name_its_own_corner(sensors: list[str], note: str) -> None:
    """The only wheel sensor feels an imbalance at any wheel, strongest where it sits.

    So the report names no wheel, says why, and asks for a sensor at each wheel
    first; it is never Strong and never swaps axles it could not compare.
    """
    summary = run_analysis(_swept_fault_samples(sensors))
    view = report_view_for(summary)
    owner = view.owner

    assert summary["diagnosis"]["zone"] is None
    assert owner.level != "strong"
    assert owner.headline == (
        "Likely cause: a wheel or tire problem that could not be pinned to one wheel"
        " (only the front-left wheel had a sensor)"
    )
    assert note in owner.description
    assert "several sensors" not in owner.description
    assert owner.next_step.startswith("Mount a sensor at each wheel")
    assert owner.confirm is None or "Swap the front and rear wheels" not in owner.confirm
    assert owner.diagram.zone is None
    texts = report_view_texts(view)
    assert not [text for text in texts if "front-left wheel balanced" in text]
    if len(sensors) == 1:
        assert "measured at the front-left wheel, the only sensor" in owner.description
        assert "strongest at" not in owner.description
    nl = report_view_for(summary, lang="nl").owner
    assert "alleen het wiel linksvoor had een sensor" in nl.headline


@pytest.mark.parametrize("measured_rpm", [False, True], ids=["no_rpm", "obd_rpm"])
def test_missing_final_drive_leaves_only_what_it_needs_untested(measured_rpm: bool) -> None:
    samples = make_fault_samples(fault_sensor="front-left", sensors=ALL_WHEEL_SENSORS)
    if measured_rpm:
        for sample in samples:
            sample.update(engine_rpm=2400.0, engine_rpm_source="obd2")
    summary = run_analysis(samples, standard_metadata(final_drive_ratio=None))
    diagnosis = summary["diagnosis"]
    checks = {
        check["source"]: (check["status"], check["reason"]) for check in diagnosis["source_checks"]
    }
    ruled_out = report_view_for(summary).mechanic.ruled_out

    # Speed and tire size alone still place the wheel orders.
    assert (diagnosis["verdict"], diagnosis["source"], diagnosis["zone"]) == (
        "fault",
        "wheel/tire",
        "front_left_wheel",
    )
    assert checks["driveline"] == ("not_testable", "no_drive_reference")
    assert "Driveline: not testable: no final-drive ratio" in ruled_out
    if measured_rpm:
        assert checks["engine"] == ("ruled_out", "no_matching_order")
        assert "Engine: no engine-order vibration found" in ruled_out
    else:
        assert checks["engine"] == ("not_testable", "no_drive_reference")
        assert "Engine: not testable: no final-drive ratio" in ruled_out


@pytest.mark.parametrize("measured_rpm", [False, True], ids=["no_rpm", "obd_rpm"])
def test_library_car_without_top_gear_leaves_only_the_speed_based_engine_check_untested(
    measured_rpm: bool,
) -> None:
    """A library row without a top gear is saved without one: never a default."""
    samples = make_fault_samples(fault_sensor="front-left", sensors=ALL_WHEEL_SENSORS)
    for sample in samples:
        sample["speed_source"] = "gps"
        if measured_rpm:
            sample.update(engine_rpm=2400.0, engine_rpm_source="obd2")
    metadata = standard_metadata(
        current_gear_ratio=None,
        active_car_snapshot={
            "fuel_type": "ICE",
            "order_reference_status": {
                "selection_source_status": "exact_row",
                "tire_dimensions_confidence": "official_exact",
                "final_drive_ratio_confidence": "official_exact",
            },
        },
    )
    summary = run_analysis(samples, metadata)
    diagnosis = summary["diagnosis"]
    checks = {
        check["source"]: (check["status"], check["reason"]) for check in diagnosis["source_checks"]
    }
    view = report_view_for(summary)
    conditions = {fact.label: fact.value for fact in view.mechanic.conditions}

    # Speed, tire size and final drive still place the wheel and driveline orders.
    assert (diagnosis["verdict"], diagnosis["source"], diagnosis["zone"]) == (
        "fault",
        "wheel/tire",
        "front_left_wheel",
    )
    assert checks["driveline"] == ("ruled_out", "no_matching_order")
    assert diagnosis["conditions"]["gear_ratio_provenance"] == "missing"
    assert conditions["Top gear ratio"] == "not provided"
    if measured_rpm:
        assert checks["engine"] == ("ruled_out", "no_matching_order")
        assert "Engine: no engine-order vibration found" in view.mechanic.ruled_out
        assert conditions["Engine RPM"] == "measured (OBD)"
    else:
        assert checks["engine"] == ("not_testable", "no_engine_reference")
        assert "Engine: not testable: no RPM or gear ratio" in view.mechanic.ruled_out
        assert "Motor: niet te testen: geen toerental of versnelling" in (
            report_view_for(summary, lang="nl").mechanic.ruled_out
        )


@pytest.mark.parametrize("measured_rpm", [False, True], ids=["no_rpm", "obd_rpm"])
def test_missing_tire_size_leaves_the_engine_testable_from_measured_rpm(
    measured_rpm: bool,
) -> None:
    samples = make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30)
    if measured_rpm:
        for sample in samples:
            sample.update(engine_rpm=2400.0, engine_rpm_source="obd2")
    summary = run_analysis(samples, standard_metadata(tire_circumference_m=None))
    checks = {
        check["source"]: (check["status"], check["reason"])
        for check in summary["diagnosis"]["source_checks"]
    }
    ruled_out = report_view_for(summary).mechanic.ruled_out

    assert summary["diagnosis"]["verdict"] == "no_fault"
    assert checks["wheel/tire"] == checks["driveline"] == ("not_testable", "no_tire_reference")
    if measured_rpm:
        assert checks["engine"] == ("ruled_out", "no_matching_order")
        assert "Engine: no engine-order vibration found" in ruled_out
    else:
        assert checks["engine"] == ("not_testable", "no_tire_reference")
        assert "Engine: not testable: no tire size" in ruled_out


@pytest.mark.parametrize(
    ("lang", "description", "not_covered"),
    [
        (
            "en",
            "Nothing stood out in the checks this run could make: wheels/tires."
            " Not checked, so not shown to be fine: driveline, engine and brakes.",
            (
                "Driveline: no final-drive ratio — add it to the car in Settings"
                " if you know it (optional).",
                "Engine: no final-drive ratio — connect an OBD-II adapter to measure RPM,"
                " or add the final drive and top-gear ratio to the car (optional).",
            ),
        ),
        (
            "nl",
            "Niets viel op bij de controles die deze rit kon doen: wielen/banden."
            " Niet gecontroleerd, dus niet aangetoond dat het in orde is: aandrijflijn, motor"
            " en remmen.",
            (
                "Aandrijflijn: geen eindoverbrenging — voeg die toe aan de auto in Instellingen"
                " als je hem weet (optioneel).",
                "Motor: geen eindoverbrenging — sluit een OBD-II-adapter aan om het toerental"
                " te meten, of voeg eindoverbrenging en hoogste versnelling toe aan de auto"
                " (optioneel).",
            ),
        ),
    ],
)
def test_no_fault_names_what_was_checked_and_what_could_not_be(
    lang: str, description: str, not_covered: tuple[str, ...]
) -> None:
    samples = make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30)
    summary = run_analysis(
        samples, standard_metadata(final_drive_ratio=None, current_gear_ratio=None)
    )
    owner = report_view_for(summary, lang=lang).owner

    assert owner.verdict == "no_fault"
    assert owner.description == description
    # Each untested source comes first in "Not covered", with how to close the gap.
    assert owner.not_covered[:2] == not_covered


def test_no_fault_with_a_faint_residual_says_it_was_found_only_faintly() -> None:
    """The run's wheel order was only at a healthy car's level: the report says
    so wherever it names the wheels, and lists no worksheet row that reads like
    a cause."""
    summary = deepcopy(_healthy_summary())
    for check in summary["diagnosis"]["source_checks"]:
        if check["source"] == "wheel/tire":
            check.update(status="ruled_out", reason="faint_only")
    view = report_view_for(summary)

    assert view.owner.headline == "No significant vibration found"
    assert "wheels/tires (found only faintly, at a level a healthy car also has)" in (
        view.owner.description
    )
    assert view.mechanic.worksheet == ()
    assert view.mechanic.worksheet_empty is not None
    assert view.mechanic.worksheet_empty.startswith("Only a faint vibration")
    assert (
        "Wheels/tires: found only faintly, at a level a healthy car also has: not a cause"
        in view.mechanic.ruled_out
    )
    nl = report_view_for(summary, lang="nl")
    assert "alleen zwak gevonden" in nl.owner.description


@pytest.mark.parametrize(
    ("lang", "fuel_type", "rpm_source", "never"),
    [
        (
            "en",
            None,
            "estimated_top_gear",
            "Never analyzed: a misfiring or unevenly running engine (a shake at half the"
            " engine speed), the firing rhythm of a six-cylinder engine (three times per"
            " engine revolution), wheel-bearing hum and shaking at a standstill with the"
            " engine idling",
        ),
        (
            "nl",
            None,
            "estimated_top_gear",
            "Nooit geanalyseerd: een motor die overslaat of onrustig loopt (een trilling op"
            " het halve motortoerental), het ontstekingsritme van een zescilindermotor (drie"
            " keer per omwenteling), brommende wiellagers en trillen bij stilstand met"
            " stationair draaiende motor",
        ),
        # Measured RPM places the engine orders at idle too.
        (
            "en",
            None,
            "measured",
            "Never analyzed: a misfiring or unevenly running engine (a shake at half the"
            " engine speed), the firing rhythm of a six-cylinder engine (three times per"
            " engine revolution) and wheel-bearing hum",
        ),
        (
            "en",
            "EV",
            "none",
            "Never analyzed: the electric motor's electrical and gear-mesh rhythms and"
            " wheel-bearing hum",
        ),
    ],
)
def test_no_fault_names_what_no_run_analyses(
    lang: str, fuel_type: str | None, rpm_source: str, never: str
) -> None:
    summary = deepcopy(_healthy_summary())
    summary["diagnosis"]["conditions"]["fuel_type"] = fuel_type
    summary["diagnosis"]["conditions"]["rpm_source"] = rpm_source

    assert report_view_for(summary, lang=lang).owner.not_covered[-1] == never


def test_no_fault_hedges_checks_that_rest_on_estimates() -> None:
    summary = deepcopy(_healthy_summary())
    summary["diagnosis"]["source_checks"] = [
        {"source": "wheel/tire", "status": "ruled_out", "reason": "no_matching_order"},
        {"source": "driveline", "status": "ruled_out_estimated", "reason": "estimated_final_drive"},
        {"source": "engine", "status": "ruled_out_estimated", "reason": "top_gear_assumed"},
    ]
    owner = report_view_for(summary).owner

    assert owner.description == (
        "Nothing stood out in the checks this run could make: wheels/tires,"
        " driveline (against an estimated final drive) and engine (top gear only)."
    )
    assert owner.not_covered[:2] == (
        "Driveline: checked only against a car-library estimate of the final drive,"
        " so not conclusive — enter the exact ratio if you know it.",
        "Engine: checked in top gear only: engine RPM was estimated from speed assuming"
        " top gear, so lower gears were not checked — an OBD-II adapter measures RPM in"
        " every gear.",
    )


@pytest.mark.parametrize(
    ("status", "reason", "owner_line", "mechanic_line"),
    [
        (
            "not_testable",
            "no_drive_reference",
            "Electric motor: no reduction ratio — add it to the car in Settings if you know"
            " it (optional).",
            "Electric motor: not testable: no reduction ratio",
        ),
        (
            "ruled_out_estimated",
            "estimated_final_drive",
            "Electric motor: checked only against a car-library estimate of the reduction"
            " ratio, so not conclusive — enter the exact ratio if you know it.",
            "Electric motor: no match with the estimated reduction ratio (car-library"
            " estimate); not conclusive",
        ),
    ],
)
def test_ev_motor_checks_name_the_reduction_ratio(
    status: str, reason: str, owner_line: str, mechanic_line: str
) -> None:
    """An EV's motor turns at wheel speed x its reduction ratio, not a final drive."""
    summary = deepcopy(_healthy_summary())
    summary["diagnosis"]["conditions"]["fuel_type"] = "EV"
    summary["diagnosis"]["source_checks"] = [
        {"source": "wheel/tire", "status": "ruled_out", "reason": "no_matching_order"},
        {"source": "driveline", "status": status, "reason": reason},
        {"source": "engine", "status": "not_applicable", "reason": "electric_car"},
    ]
    view = report_view_for(summary)

    assert view.owner.not_covered[0] == owner_line
    assert mechanic_line in view.mechanic.ruled_out


def test_braking_and_coasting_are_covered_separately() -> None:
    summary = deepcopy(_healthy_summary())
    summary["diagnosis"]["source_checks"] = [
        {"source": "wheel/tire", "status": "ruled_out", "reason": "no_matching_order"},
        {"source": "brakes", "status": "ruled_out", "reason": "no_matching_order"},
    ]
    summary["phase_info"]["phase_pcts"] = {"cruise": 40.0, "braking": 20.0, "acceleration": 40.0}
    owner = report_view_for(summary).owner

    # Firm stops checked the brakes, but the drive never coasted.
    assert owner.description == (
        "Nothing stood out in the checks this run could make: wheels/tires and brakes."
    )
    assert owner.covered is not None and "braking" in owner.covered
    assert "Coasting" in owner.not_covered
    assert not [gap for gap in owner.not_covered if "brak" in gap.lower()], owner.not_covered


@pytest.mark.parametrize(
    ("lang", "description", "gap", "mechanic"),
    [
        pytest.param(
            "en",
            "Nothing stood out in the checks this run could make: wheels/tires and brakes"
            " (may have slowed on regeneration).",
            "Brakes: an electric or plug-in hybrid car slows at up to about 0.3 g on"
            " regenerative braking, often without its brake discs, so a drive without"
            " brake judder is not conclusive — do the guided test's firm stops with"
            " regeneration at its lowest, or brake firmly with the brake pedal, harder"
            " than regeneration alone, from about 100\u00a0km/h a few times.",
            "Brakes: no once- or twice-per-wheel-turn vibration while braking, but an"
            " electric or plug-in hybrid car may have slowed on regenerative braking"
            " without its brake discs; not conclusive",
            id="en",
        ),
        pytest.param(
            "nl",
            "Niets viel op bij de controles die deze rit kon doen: wielen/banden en remmen"
            " (kan op regeneratie vertraagd hebben).",
            "Remmen: een elektrische auto of plug-in hybride remt met regeneratief remmen"
            " tot ongeveer 0,3 g af, vaak zonder de remschijven, dus een rit zonder"
            " remtrillingen is niet doorslaggevend — doe de stap stevig afremmen van de"
            " begeleide test met regeneratie op het laagste niveau, of rem een paar keer"
            " stevig met het rempedaal, harder dan regeneratie alleen, vanaf ongeveer"
            " 100\u00a0km/u.",
            "Remmen: geen trilling van één of twee keer per wielomwenteling tijdens het"
            " remmen, maar een elektrische auto of plug-in hybride kan op regeneratief"
            " remmen vertraagd hebben zonder de remschijven; niet doorslaggevend",
            id="nl",
        ),
    ],
)
def test_an_ev_that_braked_without_judder_has_its_brakes_checked_only_with_a_hedge(
    lang: str, description: str, gap: str, mechanic: str
) -> None:
    summary = deepcopy(_healthy_summary())
    summary["diagnosis"]["conditions"]["fuel_type"] = "EV"
    summary["diagnosis"]["source_checks"] = [
        {"source": "wheel/tire", "status": "ruled_out", "reason": "no_matching_order"},
        {"source": "brakes", "status": "ruled_out_estimated", "reason": "regen_braking"},
    ]
    summary["phase_info"]["phase_pcts"] = {"cruise": 60.0, "braking": 20.0, "coast_down": 20.0}
    view = report_view_for(summary, lang=lang)

    assert view.owner.description == description
    assert view.owner.not_covered[0] == gap
    assert mechanic in view.mechanic.ruled_out


def test_no_fault_without_any_reference_does_not_imply_the_car_is_fine() -> None:
    samples = make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30)
    summary = run_analysis(samples, standard_metadata(tire_circumference_m=None))
    view = report_view_for(summary)
    owner = view.owner

    # A run that compared nothing is no result: never "nothing found" or "no repair".
    assert owner.headline == "No result: this run could not check for a cause"
    assert owner.description == (
        "No vibration stood out, but this run could not check the wheels, driveline or"
        " engine against their rhythms, so it does not show that they are fine."
    )
    assert owner.next_step.startswith("Add the tire size to the car in Settings")
    assert view.mechanic.shop == (
        "This test could not check for a cause, so it neither indicates nor rules out a repair.",
    )
    assert owner.not_covered[:3] == (
        "Wheels/tires: no tire size — add it to the car in Settings.",
        "Driveline: no tire size — add it to the car in Settings.",
        "Engine: no tire size — connect an OBD-II adapter to measure RPM,"
        " or add the tire size to the car.",
    )
    conditions = {fact.label: fact.value for fact in view.mechanic.conditions}
    assert conditions["Tire size"] == "not provided"


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        (
            "en",
            {
                "Tire size": "circumference 1.984 m (entered by you)",
                "Final drive": "3.15 (car library, model-family estimate)",
                "Top gear ratio": "not provided",
                "Engine RPM": "not available",
            },
        ),
        (
            "nl",
            {
                "Bandenmaat": "omtrek 1,984 m (door jou ingevoerd)",
                "Eindoverbrenging": "3,15 (autobibliotheek, schatting voor de modelreeks)",
                "Hoogste versnelling": "niet opgegeven",
                "Motortoerental": "niet beschikbaar",
            },
        ),
    ],
)
def test_conditions_print_each_car_reference_with_its_provenance(
    lang: str, expected: dict[str, str]
) -> None:
    summary = deepcopy(_wheel_summary())
    summary["diagnosis"]["conditions"].update(
        rpm_source="none",
        tire_circumference_m=1.984,
        tire_provenance="user_confirmed",
        final_drive_ratio=3.15,
        final_drive_provenance="family_default",
        gear_ratio=None,
        gear_ratio_provenance="missing",
    )
    conditions = {
        fact.label: fact.value for fact in report_view_for(summary, lang=lang).mechanic.conditions
    }

    assert {label: conditions[label] for label in expected} == expected


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        ("en", "entered by hand (no live GPS/OBD speed)"),
        ("nl", "handmatig ingevoerd (geen live GPS/OBD-snelheid)"),
    ],
)
def test_manual_fallback_speed_source_is_named_in_plain_words(lang: str, text: str) -> None:
    samples = make_fault_samples(fault_sensor="front-left", sensors=ALL_WHEEL_SENSORS)
    for sample in samples:
        sample["speed_source"] = "fallback_manual"
    view = report_view_for(run_analysis(samples), lang=lang)

    conditions = {fact.label: fact.value for fact in view.mechanic.conditions}
    assert conditions["Speed source" if lang == "en" else "Snelheidsbron"] == text


def test_a_run_on_a_hand_typed_speed_is_no_result_and_asks_for_live_speed() -> None:
    """Every order was placed at the typed-in speed: nothing was checked."""
    samples = make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30)
    for sample in samples:
        sample["speed_source"] = "fallback_manual"
    summary = run_analysis(samples)
    view = report_view_for(summary)
    texts = report_view_texts(view)

    assert view.owner.headline == "No result: this run could not check for a cause"
    assert view.owner.next_step.startswith("Record again with live speed from GPS or an OBD-II")
    assert not [text for text in texts if "hold the speed" in text]
    assert not [text for text in texts if "No repair is indicated" in text]
    nl = report_view_for(summary, lang="nl").owner
    assert nl.headline == "Geen uitslag: deze rit kon niet op een oorzaak controleren"


def test_guided_steps_on_a_hand_typed_speed_are_named_not_checkable() -> None:
    """A typed-in speed never changes, so no tapped step shows: none was driven wrong."""
    guided = [
        {"phase": "sweep", "start_t_s": 0.0, "end_t_s": 10.0},
        {"phase": "hold", "start_t_s": 10.0, "end_t_s": 20.0},
        {"phase": "brake", "start_t_s": 20.0, "end_t_s": None},
    ]
    samples = make_engine_order_samples(sensors=ALL_WHEEL_SENSORS, speed_kmh=50.0, n_samples=30)
    for sample in samples:
        sample["speed_source"] = "manual"
    summary = run_analysis(samples, standard_metadata(guided_phases=guided))

    assert summary["diagnosis"]["guided_phases"] == []
    for lang, label, text in (
        (
            "en",
            "Guided test",
            "Not checkable with a speed entered by hand: speed sweep, steady hold, firm stops",
        ),
        (
            "nl",
            "Begeleide test",
            "Niet te controleren met een handmatig ingevoerde snelheid:"
            " snelheidsopbouw, constante snelheid, stevig afremmen",
        ),
    ):
        conditions = report_view_for(summary, lang=lang).mechanic.conditions
        assert {fact.label: fact.value for fact in conditions}[label] == text


def test_guided_steps_tapped_while_holding_one_speed_are_not_listed_as_done() -> None:
    """Tapping through the guided test at a steady 50 km/h did only the hold."""
    guided = [
        {"phase": "sweep", "start_t_s": 0.0, "end_t_s": 10.0},
        {"phase": "hold", "start_t_s": 10.0, "end_t_s": 20.0},
        {"phase": "coast_down", "start_t_s": 20.0, "end_t_s": None},
    ]
    samples = make_engine_order_samples(sensors=ALL_WHEEL_SENSORS, speed_kmh=50.0, n_samples=30)
    summary = run_analysis(samples, standard_metadata(guided_phases=guided))
    diagnosis = summary["diagnosis"]

    assert diagnosis["guided_phases"] == ["hold"]
    assert diagnosis["guided_phases_undetected"] == ["sweep", "coast_down"]
    # A coast-down that never shed speed does not decide what the vibration follows.
    assert diagnosis["speed_dependence"] is None
    for lang, label, text in (
        (
            "en",
            "Guided test",
            "steady hold; tapped but not detected: speed sweep, neutral coast-down",
        ),
        (
            "nl",
            "Begeleide test",
            "constante snelheid; aangetikt maar niet gezien in de meting:"
            " snelheidsopbouw, uitrollen in neutraal",
        ),
    ):
        conditions = report_view_for(summary, lang=lang).mechanic.conditions
        assert {fact.label: fact.value for fact in conditions}[label] == text


def test_measured_rpm_places_the_engine_markers_without_gear_ratios() -> None:
    samples = make_engine_order_samples(sensors=ALL_WHEEL_SENSORS, _engine_hz_override=50.0)
    for sample in samples:
        sample["engine_rpm_source"] = "obd2"
    summary = run_analysis(
        samples, standard_metadata(final_drive_ratio=None, current_gear_ratio=None)
    )
    spectrum = report_view_for(summary).mechanic.spectrum

    assert spectrum is not None
    markers = {marker.code: marker.hz for marker in spectrum.markers}
    assert markers["E1"] == pytest.approx(50.0)
    assert markers["E2"] == pytest.approx(100.0)
    assert "P1" not in markers


def test_spectrum_leaves_out_standstill_when_no_speed_repeats() -> None:
    # Ten one-off speeds: no 10 km/h window holds enough samples, so the spectrum
    # takes the whole drive, but the idling at 0 km/h is still left out.
    moving = [
        sample
        for index, speed in enumerate(range(30, 130, 10))
        for sample in make_fault_samples(
            fault_sensor="front-left",
            sensors=ALL_WHEEL_SENSORS,
            speed_kmh=float(speed),
            n_samples=1,
            start_t_s=index,
        )
    ]
    idling = make_noise_samples(
        sensors=ALL_WHEEL_SENSORS, speed_kmh=0.0, n_samples=10, start_t_s=10.0
    )
    view = report_view_for(run_analysis([*moving, *idling]))

    assert view.mechanic.spectrum is not None
    assert view.mechanic.spectrum.title.endswith(", 30–120\u00a0km/h"), view.mechanic.spectrum.title


def test_moderate_fault_adds_the_cheap_confirming_check() -> None:
    view = report_view_for(_driveline_summary())
    owner = view.owner

    assert owner.headline == (
        "Likely cause: the driveline (propshaft or its joints), near the rear axle"
    )
    assert owner.level_word == "Moderate"
    assert owner.level_meaning == "do the cheap confirming check first."
    assert owner.confirm is not None and "shift to neutral and coast" in owner.confirm
    assert owner.next_step.startswith("Have the propshaft checked for runout and balance")
    assert owner.diagram.zone == "rear_axle"
    assert "P1 (once per propshaft turn) points to balance or runout" in view.mechanic.shop[2]


def test_engine_fault_points_to_the_engine_bay_and_explains_e2() -> None:
    view = report_view_for(_engine_summary())
    owner = view.owner

    assert owner.headline == "Likely cause: the engine or its mounts (the engine bay)"
    assert owner.confirm is None
    assert "twice per engine revolution (the firing rhythm of a 4-cylinder)" in owner.description
    assert owner.next_step == "Have the engine and gearbox mounts checked."
    assert owner.diagram.zone == "engine_bay"
    assert view.mechanic.shop[0] == "Inspect the engine and gearbox mounts."


_INLINE_SIX = {
    "engine_profile": {"layout": "inline", "cylinders": 6},
    "engine_orders": [
        {"code": "E1", "roles": ["rotating"]},
        {"code": "E3", "roles": ["firing"]},
    ],
}
_INLINE_THREE = {
    "engine_profile": {"layout": "inline", "cylinders": 3},
    "engine_orders": [
        {"code": "E1", "roles": ["rotating", "imbalance"]},
        {"code": "E1.5", "roles": ["firing"]},
    ],
}


def _with_engine(summary: dict[str, Any], engine: dict[str, Any]) -> dict[str, Any]:
    summary["diagnosis"]["conditions"].update(deepcopy(engine))
    return summary


def test_a_known_engine_takes_its_firing_rhythm_out_of_never_analysed() -> None:
    summary = _with_engine(deepcopy(_healthy_summary()), _INLINE_SIX)

    never = report_view_for(summary).owner.not_covered[-1]

    assert "six-cylinder" not in never
    assert "misfiring" in never


def test_an_engine_fault_names_the_engines_firing_order_and_its_checks() -> None:
    summary = _with_engine(
        _variant(**{**_engine_summary()["diagnosis"], "order_code": "E3"}), _INLINE_SIX
    )

    view = report_view_for(summary)
    nl = report_view_for(summary, lang="nl")

    assert "3 times per engine revolution (the inline-6's firing rhythm)" in view.owner.description
    assert "3 keer per motoromwenteling (het ontstekingsritme van de 6-in-lijn)" in (
        nl.owner.description
    )
    assert view.owner.next_step.startswith("Have the engine and gearbox mounts checked")
    assert "misfire" in view.owner.next_step
    assert any("Compare E1 and E3 under load" in line for line in view.mechanic.shop)
    assert ("Engine", "Inline-6, fires at E3") in [
        (fact.label, fact.value) for fact in view.mechanic.conditions
    ]


def test_an_inline_threes_half_order_and_built_in_imbalance_read_in_plain_words() -> None:
    firing = _with_engine(
        _variant(**{**_engine_summary()["diagnosis"], "order_code": "E1.5"}), _INLINE_THREE
    )
    imbalance = _with_engine(
        _variant(**{**_engine_summary()["diagnosis"], "order_code": "E1"}), _INLINE_THREE
    )

    assert "1.5 times per engine revolution (the inline-3's firing rhythm)" in (
        report_view_for(firing).owner.description
    )
    assert "1,5 keer per motoromwenteling" in report_view_for(firing, lang="nl").owner.description
    imbalance_view = report_view_for(imbalance)
    assert "(the inline-3's built-in imbalance)" in imbalance_view.owner.description
    assert imbalance_view.owner.next_step.startswith("Have the engine and gearbox mounts checked")
    assert "balance shaft" in (imbalance_view.owner.fallback_step or "")


def test_an_engine_order_on_the_propshafts_rhythm_names_both_and_how_to_tell_them_apart() -> None:
    summary = _with_engine(
        _variant(
            **{
                **_engine_summary()["diagnosis"],
                "order_code": "E3",
                "confidence_level": "moderate",
                "alternative": {"source": "driveline", "order_code": "P2"},
            }
        ),
        _INLINE_SIX,
    )
    for check in summary["diagnosis"]["source_checks"]:
        if check["source"] == "driveline":
            check.update(status="not_testable", reason="same_rhythm_as_candidate")

    view = report_view_for(summary)

    assert view.owner.headline == (
        "Likely cause: the engine or its mounts (the engine bay), or the propshaft (P2)"
    )
    assert "cannot be told apart from the propshaft (P2)" in view.owner.description
    assert view.owner.confirm is not None and "shift to neutral and coast" in view.owner.confirm
    assert (view.owner.fallback_step or "").startswith(
        "If the neutral coast-down points to the other cause: Have the propshaft joints"
    )
    assert view.mechanic.shop[0].startswith("E3 and P2 sit at the same frequency in top gear")
    assert any(
        line.startswith("Driveline: not told apart: without measured RPM the engine")
        for line in view.mechanic.ruled_out
    )
    nl = report_view_for(summary, lang="nl")
    assert nl.owner.headline.endswith(", of de cardanas (P2)")


def test_a_propshaft_order_on_the_engines_firing_rhythm_names_the_firing_rhythm() -> None:
    summary = _with_engine(
        _variant(
            **{
                **_driveline_summary()["diagnosis"],
                "order_code": "P2",
                "alternative": {"source": "engine", "order_code": "E3"},
            }
        ),
        _INLINE_SIX,
    )

    view = report_view_for(summary)

    assert view.owner.headline.endswith(", or the inline-6's firing rhythm (E3)")
    assert "Without measured engine RPM" in view.owner.description
    assert "in some gear it turns at this same rhythm" not in view.owner.description


def test_the_spectrum_labels_the_firing_order() -> None:
    summary = _with_engine(deepcopy(_wheel_summary()), _INLINE_SIX)
    spectrum = summary["diagnosis"]["spectrum"]
    engine = spectrum["order_markers"]["E1"]
    spectrum["order_markers"] = {
        code: hz for code, hz in spectrum["order_markers"].items() if code != "E2"
    } | {"E3": 3 * engine}

    chart = report_view_for(summary).mechanic.spectrum

    assert chart is not None
    labels = {marker.code: marker.label for marker in chart.markers}
    assert labels["E3"] == "E3 firing"
    assert labels["E1"] == "E1"
    assert chart.x_max_hz >= 3 * engine


def test_weak_evidence_hedges_candidate_with_reasons_and_recapture_recipe() -> None:
    view = report_view_for(_weak_summary())
    owner = view.owner

    assert owner.headline == "Not enough evidence to name a cause"
    assert owner.candidate == (
        "Best guess, not confirmed: a wheel or tire problem at the front wheels."
    )
    assert owner.level_word == "Weak"
    assert owner.reasons[0].startswith("The vibration was about as strong at several sensors")
    assert owner.reasons[1].startswith("The speed hardly changed")
    assert owner.recapture == (
        "Use a smooth, straight road.",
        "Accelerate slowly from 50 to 120\u00a0km/h.",
        "Hold steady for 20 seconds at the speed where you feel it most.",
        "From that speed, shift to neutral and coast down.",
    )
    assert owner.verify is None
    assert view.mechanic.shop == (
        "Don't replace parts based on this report alone; record the test again first.",
    )


def _not_checked_summary() -> dict[str, Any]:
    return run_analysis(
        make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30),
        standard_metadata(tire_circumference_m=None),
    )


def _unexplained_summary() -> dict[str, Any]:
    summary = deepcopy(_healthy_summary())
    summary["diagnosis"].update(
        unexplained_vibration=True,
        location_amplitudes=[
            {
                "location": "Rear Right Wheel",
                "amplitude_mg": 228.5,
                "db_above_floor": 36.5,
                "ratio_to_strongest": 1.0,
                "presence_ratio": None,
            }
        ],
    )
    return summary


@pytest.mark.parametrize(
    ("summary", "en", "nl", "tone"),
    [
        pytest.param(
            _healthy_summary,
            "No significant vibration",
            "Geen noemenswaardige trilling",
            "good",
            id="no-fault",
        ),
        pytest.param(_not_checked_summary, "No result", "Geen uitslag", "muted", id="not-checked"),
        pytest.param(
            _unexplained_summary,
            "Unexplained vibration",
            "Onverklaarde trilling",
            "muted",
            id="unexplained",
        ),
        pytest.param(_weak_summary, "Not conclusive", "Niet doorslaggevend", "muted", id="weak"),
        pytest.param(_engine_summary, "Engine", "Motor", "strong", id="engine"),
        pytest.param(
            lambda: _variant(zone="front_axle", confidence_level="moderate"),
            "Front wheels",
            "Voorwielen",
            "moderate",
            id="wheel-axle",
        ),
        pytest.param(
            lambda: _variant(source="brakes", zone="rear_axle", confidence_level="strong"),
            "Rear brake discs",
            "Remschijven achter",
            "strong",
            id="brake-axle",
        ),
        pytest.param(
            lambda: _variant(
                source="engine",
                order_code="E3",
                zone="engine_bay",
                confidence_level="moderate",
                alternative={"source": "driveline", "order_code": "P2"},
            ),
            "Engine or driveline",
            "Motor of aandrijflijn",
            "moderate",
            id="engine-or-driveline",
        ),
    ],
)
def test_owner_page_names_the_result_for_history_and_the_verdict_color(
    summary: Any, en: str, nl: str, tone: str
) -> None:
    """History titles a run with the result, and both draw the verdict box in one tone."""
    analysis = summary()
    owner = report_view_for(analysis).owner

    assert (owner.result, owner.tone) == (en, tone)
    assert report_view_for(analysis, lang="nl").owner.result == nl
    # History's page 1 is the PDF's page 1.
    assert build_owner_page(analysis, lang="en") == owner


def test_a_clear_wheel_fault_names_its_corner_and_level() -> None:
    summary = _wheel_summary()
    owner = report_view_for(summary).owner

    assert owner.result == "Front-left wheel"
    assert owner.tone == summary["diagnosis"]["confidence_level"]
    assert report_view_for(summary, lang="nl").owner.result == "Wiel linksvoor"


def test_dutch_view_translates_and_uses_decimal_commas() -> None:
    view = report_view_for(_wheel_summary(), lang="nl")
    owner = view.owner

    assert view.title == "VibeSensor-trillingsrapport"
    assert (
        owner.headline
        == "Waarschijnlijke oorzaak: een wiel- of bandprobleem bij het wiel linksvoor"
    )
    assert "10,4 Hz" in owner.description
    assert owner.next_step.startswith("Laat het wiel linksvoor balanceren")
    assert view.mechanic.amplitudes[0].location == "wiel linksvoor"
    assert view.page_label(1, 2) == "Pagina 1 van 2"


def test_requested_language_wins_over_the_runs_language() -> None:
    summary = deepcopy(_wheel_summary())
    summary["lang"] = "nl"

    assert report_view_for(summary, lang="en").lang == "en"


def test_report_date_shows_in_the_users_time_zone_not_the_recorded_offset() -> None:
    summary = deepcopy(_wheel_summary())
    summary["start_time_utc"] = "2025-07-01T10:00:00Z"
    metadata = run_metadata_from_mapping(
        {**summary["metadata"], "run_id": "run", "recorded_utc_offset_seconds": 0}
    )

    def dates(time_zone: str | None) -> list[str]:
        view = build_report_view(summary, metadata, lang="en", time_zone=time_zone)
        return [fact.value for fact in view.header if fact.value.startswith("2025-")]

    assert dates("Europe/Amsterdam") == ["2025-07-01 12:00:00 UTC+02:00"]
    assert dates(None) == ["2025-07-01 10:00:00 UTC"]


def test_report_date_is_unknown_when_the_run_started_before_the_pi_clock_was_set() -> None:
    summary = deepcopy(_wheel_summary())
    summary["start_time_utc"] = "2025-07-01T10:00:00Z"
    metadata = run_metadata_from_mapping(
        {**summary["metadata"], "run_id": "run", "start_time_unverified": True}
    )

    def date(lang: str) -> str:
        view = build_report_view(summary, metadata, lang=lang, time_zone=None)
        return view.header[2].value

    assert date("en") == "not verified (the Pi clock was not set)"
    assert date("nl") == "niet geverifieerd (de klok van de Pi was niet gezet)"


def test_quality_collapses_to_one_footer_line_only_when_everything_passed() -> None:
    summary = deepcopy(_wheel_summary())
    summary["warnings"] = []
    for check in summary["run_suitability"]:
        check["state"] = "pass"
    passed = report_view_for(summary).quality

    assert passed.all_passed
    assert passed.footer_line.startswith("All data checks passed · Run ")

    summary["warnings"] = [
        {
            "code": "raw_replay_dropped_chunks",
            "severity": "warn",
            "applies_to": "raw_capture",
            "title": {"_i18n_key": "RUN_CONTEXT_WARNING_RAW_REPLAY_DROPPED_CHUNKS_TITLE"},
        }
    ]
    warned = report_view_for(summary).quality

    assert not warned.all_passed
    assert warned.warnings == ("Some sensor data packets were lost during recording.",)


def test_quality_warning_states_each_check_once_and_keeps_measured_counts() -> None:
    summary = deepcopy(_wheel_summary())
    states = {
        "SUITABILITY_CHECK_SENSOR_COVERAGE": ("SUITABILITY_SENSOR_COVERAGE_WARN", {}),
        "SUITABILITY_CHECK_FRAME_INTEGRITY": (
            "SUITABILITY_FRAME_INTEGRITY_WARN",
            {"total_dropped": 3, "total_overflow": 1},
        ),
        "SUITABILITY_CHECK_SPEED_VARIATION": ("SUITABILITY_SPEED_VARIATION_WARN", {}),
    }
    for check in summary["run_suitability"]:
        if check["check_key"] in states:
            key, params = states[check["check_key"]]
            check["state"] = "warn"
            check["explanation"] = {"_i18n_key": key, **params}
    details = {
        lang: {c.label: c.detail for c in report_view_for(summary, lang=lang).quality.checks}
        for lang in ("en", "nl")
    }

    assert details["en"]["Sensor coverage"] == (
        "Few sensors were active, so the location is less certain."
    )
    assert details["nl"]["Sensordekking"] == (
        "Er waren weinig sensoren actief, dus de locatie is minder zeker."
    )
    assert details["en"]["Frame integrity"] == (
        "Some sensor data was lost or incomplete. 3 dropped frames, 1 queue overflows detected."
    )
    assert details["en"]["Speed variation"] == (
        "The speed could not tell the wheel and drivetrain orders apart. "
        "Too little of the run had a known speed; record with GPS or OBD-II speed above"
        " 20\u00a0km/h."
    )
    assert details["nl"]["Snelheidsvariatie"].endswith("boven 20\u00a0km/u.")
    in_mps = {
        lang: {
            c.label: c.detail
            for c in report_view_for(summary, lang=lang, speed_unit="mps").quality.checks
        }
        for lang in ("en", "nl")
    }
    assert in_mps["en"]["Speed variation"].endswith("speed above 6\u00a0m/s.")
    assert in_mps["nl"]["Snelheidsvariatie"].endswith("boven 6\u00a0m/s.")


def test_a_steady_speed_reads_as_one_speed_not_a_range() -> None:
    summary = deepcopy(_wheel_summary())
    summary["speed_stats"].update(min_kmh=50.0, max_kmh=50.0)
    summary["diagnosis"].update(speed_min_kmh=50.0, speed_max_kmh=50.0)
    summary["diagnosis"]["spectrum"].update(speed_min_kmh=50.0, speed_max_kmh=50.0)
    view = report_view_for(summary)
    text = _all_text(view)

    assert "50–50" not in text
    assert "present at 50\u00a0km/h" in view.owner.description
    assert view.mechanic.spectrum is not None
    assert view.mechanic.spectrum.title.endswith(", 50\u00a0km/h")
    healthy = report_view_for(_healthy_summary())
    assert healthy.owner.covered is not None and "–" not in healthy.owner.covered.split("(")[0]


@pytest.mark.parametrize(
    ("lang", "speed_unit", "confirm", "recapture"),
    [
        (
            "en",
            "kmh",
            "On a quiet road, brake firmly from about 100\u00a0km/h a few times.",
            "From about 100\u00a0km/h, brake firmly down to 40\u00a0km/h a few times,",
        ),
        (
            "en",
            "mps",
            "On a quiet road, brake firmly from about 28\u00a0m/s a few times.",
            "From about 28\u00a0m/s, brake firmly down to 11\u00a0m/s a few times,",
        ),
        (
            "nl",
            "kmh",
            "Rem op een rustige weg een paar keer stevig af vanaf ongeveer 100\u00a0km/u.",
            "Rem vanaf ongeveer 100\u00a0km/u een paar keer stevig af tot 40\u00a0km/u,",
        ),
        (
            "nl",
            "mps",
            "Rem op een rustige weg een paar keer stevig af vanaf ongeveer 28\u00a0m/s.",
            "Rem vanaf ongeveer 28\u00a0m/s een paar keer stevig af tot 11\u00a0m/s,",
        ),
    ],
)
def test_brake_tips_name_the_speeds_in_the_users_unit(
    lang: str, speed_unit: str, confirm: str, recapture: str
) -> None:
    brakes = {"source": "brakes", "zone": "front_axle", "dominant_phase": "braking"}
    moderate = report_view_for(
        _variant(**brakes, confidence_level="moderate"), lang=lang, speed_unit=speed_unit
    )
    weak = report_view_for(
        _variant(**brakes, verdict="weak_evidence", confidence_level="weak"),
        lang=lang,
        speed_unit=speed_unit,
    )

    assert moderate.owner.confirm is not None
    assert moderate.owner.confirm.startswith(confirm)
    assert weak.owner.recapture[1].startswith(recapture)


def test_a_report_in_metres_per_second_shows_every_speed_in_metres_per_second() -> None:
    summary = _variant(
        amplitude_vs_speed=[
            {"speed_kmh": 54.0, "location": "front-left", "amplitude_mg": 40.0},
            {"speed_kmh": 90.0, "location": "front-left", "amplitude_mg": 90.0},
        ]
    )
    too_little_speed = _weak_summary()
    for check in too_little_speed["run_suitability"]:
        if check["check_key"] == "SUITABILITY_CHECK_SPEED_VARIATION":
            check["state"] = "warn"
            check["explanation"] = {"_i18n_key": "SUITABILITY_SPEED_VARIATION_WARN"}
    for variant in (summary, _weak_summary(), _healthy_summary(), too_little_speed):
        for lang in ("en", "nl"):
            texts = report_view_texts(report_view_for(variant, lang=lang, speed_unit="mps"))
            assert not [text for text in texts if "km/" in text]
    warned = report_view_texts(report_view_for(too_little_speed, speed_unit="mps"))
    assert [text for text in warned if text.endswith("speed above 6\u00a0m/s.")]
    chart = report_view_for(summary, speed_unit="mps").mechanic.speed_chart
    assert chart is not None
    assert chart.speed_unit == "m/s"
    assert chart.series[0].points == ((15.0, 40.0), (25.0, 90.0))


def test_speed_chart_only_when_the_speed_range_was_swept() -> None:
    swept = _variant(
        amplitude_vs_speed=[
            {"speed_kmh": 52.5, "location": "front-left", "amplitude_mg": 40.0},
            {"speed_kmh": 92.5, "location": "front-left", "amplitude_mg": 90.0},
        ]
    )
    held = _variant(
        amplitude_vs_speed=[
            {"speed_kmh": 77.5, "location": "front-left", "amplitude_mg": 40.0},
            {"speed_kmh": 82.5, "location": "front-left", "amplitude_mg": 45.0},
        ]
    )

    assert report_view_for(swept).mechanic.speed_chart is not None
    assert report_view_for(held).mechanic.speed_chart is None


@pytest.mark.parametrize(
    ("lang", "follows", "ruled_out", "guided"),
    [
        (
            "en",
            "It follows road speed: it kept going while coasting in neutral.",
            "Engine: ruled out: the vibration kept going while coasting in neutral",
            "speed sweep, steady hold, neutral coast-down, firm stops",
        ),
        (
            "nl",
            "Hij volgt de rijsnelheid: hij bleef bij uitrollen in neutraal.",
            "uitgesloten: de trilling bleef bij uitrollen in neutraal",
            "snelheidsopbouw, constante snelheid, uitrollen in neutraal, stevig afremmen",
        ),
    ],
)
def test_guided_coast_down_classifies_the_vibration(
    lang: str, follows: str, ruled_out: str, guided: str
) -> None:
    view = report_view_for(_guided_summary(), lang=lang)

    assert view.owner.description.endswith(follows)
    assert any(ruled_out in line for line in view.mechanic.ruled_out)
    conditions = {fact.label: fact.value for fact in view.mechanic.conditions}
    assert guided in conditions.values()


def test_contradicting_coast_down_is_a_plain_weak_reason() -> None:
    view = report_view_for(_guided_contradiction_summary(), lang="en")

    assert view.owner.description.endswith(
        "It follows engine speed: it stopped while coasting in neutral."
    )
    assert (
        "The neutral coast-down points to a different source than the frequency does."
        in view.owner.reasons
    )


def test_unguided_run_says_the_guided_test_was_not_used() -> None:
    view = report_view_for(_wheel_summary(), lang="en")

    conditions = {fact.label: fact.value for fact in view.mechanic.conditions}
    assert conditions["Guided test"] == "not used"
    assert "neutral" not in view.owner.description


def test_guided_coast_down_replaces_the_neutral_cheap_check() -> None:
    engine = _engine_summary()
    engine["diagnosis"].update(confidence_level="moderate")
    unguided = report_view_for(engine, lang="en").owner
    engine["diagnosis"].update(guided_phases=["coast_down"], speed_dependence="engine_speed")
    guided = report_view_for(engine, lang="en").owner

    assert unguided.confirm is not None and "neutral" in unguided.confirm
    assert guided.confirm is None
    assert guided.level_meaning == "the neutral coast-down in this test already backs it up."


def test_a_run_with_a_power_dip_and_overheating_says_its_results_may_be_affected() -> None:
    """Stored by the recorder (power/monitor.py), stated on the PDF and in History."""
    summary = run_analysis(
        make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30),
        power_issues=["undervoltage", "overheated"],
    )

    pdf = {lang: report_view_for(summary, lang=lang).quality for lang in ("en", "nl")}
    history = localize_warning_list(summary["warnings"], lang="nl")

    assert not pdf["en"].all_passed
    assert {
        "Power dipped during this run; results may be affected",
        "The Pi overheated during this run; results may be affected",
    } <= set(pdf["en"].warnings)
    nl_dip = "De voeding zakte weg tijdens deze meting; de uitkomst kan afwijken"
    assert nl_dip in pdf["nl"].warnings
    power = [row for row in history if str(row["code"]).startswith("power_")]
    assert [(row["code"], row["detail"]) for row in power] == [
        (
            "power_undervoltage",
            "De voedingsspanning van de Pi was te laag. Gebruik een sterkere USB-poort "
            "of een 5 V / 2,5 A auto-adapter.",
        ),
        (
            "power_overheated",
            "Hij werd heter dan 80 °C en ging trager werken. Houd hem uit de zon en weg "
            "van de verwarming.",
        ),
    ]


def test_the_cause_felt_in_the_trunk_says_its_share_and_that_a_workshop_acts_on_it() -> None:
    view = report_view_for(_felt_trunk_summary(), lang="en")
    owner, mechanic = view.owner, view.mechanic

    assert owner.felt_title == "What you feel"
    assert owner.felt is not None
    assert owner.felt.startswith(
        "This cause explains most of what the test measured at the trunk, nearest where you"
        " sit, at 80–120\xa0km/h. A workshop acts on that level: from 25\xa0mg at the driver's"
        " seat, GM has the wheels balanced and road-force checked."
    )
    # The trunk is not the seat track the limit is measured on.
    assert "is not the seat workshops measure at" in owner.felt
    assert mechanic.felt_title == "What the driver feels: levels at the trunk"
    first, second = mechanic.felt
    assert (first.cause, first.level, first.share, first.judged, first.workshop) == (
        "Wheels/tires (T1, T2)",
        "60\xa0mg",
        "80\xa0%",
        "At workshop level",
        "25\xa0mg",
    )
    assert first.first and not second.first
    assert second.judged == "Below workshop level"
    assert mechanic.felt_note is not None and "19-NA-240" in mechanic.felt_note


@pytest.mark.parametrize(
    ("summary", "felt"),
    [
        (
            lambda: _felt_summary("Driver Seat", _felt_row("wheel/tire", ["T1"], 15.0)),
            "That level is below the 25\xa0mg at the driver's seat from which workshops act:"
            " what you feel may also come from something else. A workshop may find the wheels"
            " in balance; ask for a road-force check of the tires as well.",
        ),
        (
            _felt_engine_normal_summary,
            "That level is normal for an engine (2.0\xa0mg or less at the driver's seat): what"
            " you feel may come from something else.",
        ),
        (
            lambda: _felt_summary("Trunk", _felt_row("wheel/tire", ["T1"], 0.0)),
            "It was not measurable at the trunk, nearest where you sit, so it may not be what"
            " you feel.",
        ),
        (
            lambda: _felt_summary(None),
            "This run had no sensor in the cabin or the trunk, so this report cannot say how"
            " much of what you feel this cause explains.",
        ),
    ],
)
def test_the_felt_wording_says_when_the_cause_may_not_be_what_is_felt(
    summary: Any, felt: str
) -> None:
    owner = report_view_for(summary(), lang="en").owner

    assert owner.felt is not None and felt in owner.felt
    # A seat is where workshops measure: no caveat there.
    assert "is not the seat" not in owner.felt


def test_a_no_fault_run_says_nothing_about_what_is_felt() -> None:
    view = report_view_for(_healthy_summary(), lang="en")

    assert view.owner.felt is None and view.mechanic.felt_title is None
