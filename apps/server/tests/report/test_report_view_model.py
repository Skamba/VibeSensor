"""Report view model: every page-1/page-2 string for each verdict variant, in en and nl."""

from __future__ import annotations

import re
from copy import deepcopy
from functools import cache
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

from vibesensor.recording.run_metadata import run_metadata_from_mapping
from vibesensor.report.view_model import ReportView, build_report_view

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


def _guided_summary() -> dict[str, Any]:
    summary = _variant(
        guided_phases=["sweep", "hold", "coast_down"], speed_dependence="vehicle_speed"
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
        " Not checked, so not shown to be fine: engine."
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
    assert mechanic.shop[0].startswith("Road-force all four wheel/tire assemblies")
    assert any(line.startswith("Driveline: ") for line in mechanic.ruled_out)
    assert not any(line.startswith("Wheels/tires") for line in mechanic.ruled_out)


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
            " Not checked, so not shown to be fine: driveline and engine.",
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
            " Niet gecontroleerd, dus niet aangetoond dat het in orde is: aandrijflijn en motor.",
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


def test_no_fault_without_any_reference_does_not_imply_the_car_is_fine() -> None:
    samples = make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30)
    summary = run_analysis(samples, standard_metadata(tire_circumference_m=None))
    view = report_view_for(summary)
    owner = view.owner

    assert owner.headline == "No significant vibration found"
    assert owner.description == (
        "No vibration stood out, but this run could not check the wheels, driveline or"
        " engine against their rhythms, so it does not show that they are fine."
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


def test_measured_rpm_places_the_engine_markers_without_gear_ratios() -> None:
    samples = make_engine_order_samples(sensors=ALL_WHEEL_SENSORS, _engine_hz_override=50.0)
    for sample in samples:
        sample["engine_rpm_source"] = "obd2"
    summary = run_analysis(
        samples, standard_metadata(final_drive_ratio=None, current_gear_ratio=None)
    )
    spectrum = report_view_for(summary).mechanic.spectrum

    assert spectrum is not None
    markers = dict(spectrum.markers)
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
        "Accelerate slowly from 50 to 120 km/h.",
        "Hold steady for 20 seconds at the speed where you feel it most.",
        "From that speed, shift to neutral and coast down.",
    )
    assert owner.verify is None
    assert view.mechanic.shop == (
        "Don't replace parts based on this report alone; record the test again first.",
    )


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
        "Too little of the run had a known speed; record with GPS or OBD-II speed above 20 km/h."
    )


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
            "speed sweep, steady hold, neutral coast-down",
        ),
        (
            "nl",
            "Hij volgt de rijsnelheid: hij bleef bij uitrollen in neutraal.",
            "uitgesloten: de trilling bleef bij uitrollen in neutraal",
            "snelheidsopbouw, constante snelheid, uitrollen in neutraal",
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
