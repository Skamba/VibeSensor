"""Docker E2E: a recorded run's persisted diagnosis names the verdict the UI and PDF show."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from tests_e2e._docker_edge_helpers import _cleanup_run, _simulate, _wait_complete
from tests_e2e.e2e_helpers import (
    api_json,
    pdf_text,
    remove_all_clients,
    run_simulator,
    sim_client_ids,
    wait_report_pdf_ready,
)
from vibesensor.domain.analysis_settings import ANALYSIS_SETTINGS_DEFAULTS

pytestmark = pytest.mark.e2e

# Covers the first clock-sync exchanges plus several analysis windows at speed.
_SIM_DURATION_S = 18.0
# One pass of a guided scenario: sweep, hold, then a neutral coast-down.
_GUIDED_DURATION_S = 25.0


def _record(
    e2e_env: dict[str, str],
    scenario: str,
    *,
    duration_s: float = _SIM_DURATION_S,
    before_stop: Callable[[dict], None] | None = None,
    names: str | None = None,
    keep_clients: bool = False,
) -> tuple[str, dict]:
    """Record *scenario*; *before_stop* sees the live recording status before the stop."""
    base = e2e_env["base_url"]
    if not keep_clients:
        remove_all_clients(base)
    run_id = str(api_json(base, "/api/recording/start", method="POST")["run_id"])
    run_simulator(
        base_url=base,
        sim_host=e2e_env["sim_host"],
        sim_data_port=e2e_env["sim_data_port"],
        sim_control_port=e2e_env["sim_control_port"],
        client_control_base=e2e_env["sim_client_control_base"],
        duration_s=duration_s,
        count=4,
        scenario=scenario,
        fault_wheel="rear-left",
        speed_kmh=80.0,
        **({"names": names} if names is not None else {}),
    )
    if before_stop is not None:
        before_stop(api_json(base, "/api/recording/status"))
    api_json(base, "/api/recording/stop", method="POST")
    run = _wait_complete(base, run_id)
    assert run["status"] == "complete", run
    return run_id, api_json(base, f"/api/history/{run_id}/insights")


def test_fault_free_run_reports_no_significant_vibration_e2e(e2e_env: dict[str, str]) -> None:
    run_id, insights = _record(e2e_env, "road-fixed")
    try:
        diagnosis = insights["diagnosis"]
        assert diagnosis["verdict"] == "no_fault", diagnosis
        assert diagnosis["confidence_level"] is None
        assert diagnosis["source"] is None
        assert diagnosis["amplitude_basis"] == "overall"
        assert len(diagnosis["location_amplitudes"]) == 4
        pdf = pdf_text(wait_report_pdf_ready(e2e_env["base_url"], run_id).body)
        assert "no significant vibration found" in pdf
        assert "%" not in pdf.split("for the workshop")[0]
    finally:
        _cleanup_run(e2e_env["base_url"], run_id)
        remove_all_clients(e2e_env["base_url"])


# Advertised names in an order unrelated to the location order, so the run must
# join each MAC to its assigned location rather than to its index or its name.
_WHEEL_SENSOR_NAMES = ("VS-1 rear right", "VS-2 front left", "VS-3 rear left", "VS-4 front right")
_WHEEL_LOCATION_CODES = (
    "rear_right_wheel",
    "front_left_wheel",
    "rear_left_wheel",
    "front_right_wheel",
)


def _register_and_place_wheel_sensors(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    remove_all_clients(base)
    _simulate(e2e_env, duration=2.0, count=4, names=",".join(_WHEEL_SENSOR_NAMES))
    for client_id, code in zip(sim_client_ids(4), _WHEEL_LOCATION_CODES, strict=True):
        api_json(
            base,
            f"/api/clients/{client_id}/location",
            method="POST",
            body={"location_code": code},
        )


def test_wheel_fault_run_names_corner_order_level_and_mg_amplitudes_e2e(
    e2e_env: dict[str, str],
) -> None:
    base = e2e_env["base_url"]
    _register_and_place_wheel_sensors(e2e_env)
    run_id, insights = _record(
        e2e_env, "one-wheel-mild", names=",".join(_WHEEL_SENSOR_NAMES), keep_clients=True
    )
    try:
        diagnosis = insights["diagnosis"]
        # The simulator puts the imbalance on the sensor advertised as "rear left".
        assert diagnosis["verdict"] == "fault", diagnosis
        assert diagnosis["confidence_level"] in {"strong", "moderate"}, diagnosis
        assert diagnosis["source"] == "wheel/tire"
        assert diagnosis["order_code"] == "T1"
        assert diagnosis["location"] == "Rear Left Wheel", diagnosis
        assert diagnosis["zone"] == "rear_left_wheel", diagnosis
        strongest = diagnosis["location_amplitudes"][0]
        assert strongest["location"] == "Rear Left Wheel"
        assert strongest["amplitude_mg"] > 0
        assert strongest["ratio_to_strongest"] == 1.0
        assert strongest["db_above_floor"] is not None
        assert {row["location"] for row in diagnosis["location_amplitudes"]} == {
            "Rear Left Wheel",
            "Rear Right Wheel",
            "Front Left Wheel",
            "Front Right Wheel",
        }
        # One confidence expression only: levels, never percentages.
        for finding in insights["findings"]:
            assert finding["confidence_level"] in {"strong", "moderate", "weak"}
            assert "confidence_pct" not in finding
        metadata = api_json(base, f"/api/history/{run_id}")["analysis"]["analysis_metadata"]
        assert metadata["raw_capture_mode"] in {"raw_backed", "partial_raw_backed"}
        assert metadata["raw_backed_sample_count"] > 0

        pdf = " ".join(pdf_text(wait_report_pdf_ready(base, run_id).body).split())
        assert "likely cause: a wheel or tire problem at the rear-left wheel" in pdf, pdf[:400]
        assert diagnosis["confidence_level"] in pdf
        assert "once per wheel turn" in pdf
        assert " mg" in pdf
        pdf_nl = " ".join(pdf_text(wait_report_pdf_ready(base, run_id, lang="nl").body).split())
        assert "waarschijnlijke oorzaak: een wiel- of bandprobleem bij het wiel linksachter" in (
            pdf_nl
        ), pdf_nl[:400]
        assert "één keer per wielomwenteling" in pdf_nl
    finally:
        _cleanup_run(base, run_id)
        remove_all_clients(base)


@pytest.fixture
def _distinct_orders_car(e2e_env: dict[str, str]) -> Iterator[None]:
    """A car whose engine orders sit apart from the wheel orders and the idle tones.

    With the default 3.08 x 0.64 ratios the first engine order lands on the
    second wheel order, so the coast-down could not tell the two apart.
    """
    base = e2e_env["base_url"]
    before = api_json(base, "/api/settings/cars")
    created = api_json(
        base,
        "/api/settings/cars",
        method="POST",
        body={
            "name": "Guided test car",
            "type": "hatchback",
            "aspects": {
                "tire_width_mm": 225.0,
                "tire_aspect_pct": 45.0,
                "rim_in": 17.0,
                "final_drive_ratio": 3.4,
                "current_gear_ratio": 0.8,
            },
        },
    )
    car_id = next(
        str(car["id"])
        for car in created["cars"]
        if str(car["id"]) not in {str(old["id"]) for old in before["cars"]}
    )
    api_json(base, "/api/settings/cars/active", method="PUT", body={"car_id": car_id})
    try:
        yield
    finally:
        previous = before["active_car_id"]
        if previous is not None:
            api_json(base, "/api/settings/cars/active", method="PUT", body={"car_id": previous})
            api_json(base, f"/api/settings/cars/{car_id}", method="DELETE")
        else:
            # The last car can't be deleted: put the default geometry back instead.
            api_json(
                base,
                "/api/settings/analysis",
                method="PUT",
                body={
                    key: ANALYSIS_SETTINGS_DEFAULTS[key]
                    for key in (
                        "tire_width_mm",
                        "tire_aspect_pct",
                        "rim_in",
                        "final_drive_ratio",
                        "current_gear_ratio",
                    )
                },
            )


@pytest.mark.usefixtures("_distinct_orders_car")
@pytest.mark.parametrize(
    ("scenario", "source", "follows", "ruled_out", "sentence"),
    [
        (
            "guided-wheel-coastdown",
            "wheel/tire",
            "vehicle_speed",
            {"engine": "stayed_in_neutral"},
            "it follows road speed",
        ),
        (
            "guided-engine-coastdown",
            "engine",
            "engine_speed",
            {"wheel/tire": "stopped_in_neutral"},
            "it follows engine speed",
        ),
    ],
)
def test_guided_coast_down_classifies_what_the_vibration_follows_e2e(
    e2e_env: dict[str, str],
    scenario: str,
    source: str,
    follows: str,
    ruled_out: dict[str, str],
    sentence: str,
) -> None:
    live_status: list[dict] = []
    run_id, insights = _record(
        e2e_env, scenario, duration_s=_GUIDED_DURATION_S, before_stop=live_status.append
    )
    try:
        # What a Live page reloaded mid-run restores the guided panel from.
        completed = live_status[0]["guided_phases_completed"]
        assert completed[:2] == ["sweep", "hold"], live_status
        run = api_json(e2e_env["base_url"], f"/api/history/{run_id}")
        marked = [step["phase"] for step in run["metadata"]["guided_phases"]]
        assert marked[:3] == ["sweep", "hold", "coast_down"], marked
        diagnosis = insights["diagnosis"]
        assert diagnosis["source"] == source, diagnosis
        assert diagnosis["guided_phases"][:3] == ["sweep", "hold", "coast_down"]
        assert diagnosis["speed_dependence"] == follows, diagnosis
        checks = {check["source"]: check["reason"] for check in diagnosis["source_checks"]}
        for excluded, reason in ruled_out.items():
            assert checks[excluded] == reason, checks
        pdf = " ".join(pdf_text(wait_report_pdf_ready(e2e_env["base_url"], run_id).body).split())
        assert sentence in pdf
        assert "neutral coast-down" in pdf
    finally:
        _cleanup_run(e2e_env["base_url"], run_id)
        remove_all_clients(e2e_env["base_url"])
