"""Docker E2E: a recorded run's persisted diagnosis names the verdict the UI and PDF show."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from tests_e2e._docker_edge_helpers import _cleanup_run, _wait_complete
from tests_e2e.e2e_helpers import (
    api_json,
    pdf_text,
    remove_all_clients,
    run_simulator,
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
) -> tuple[str, dict]:
    """Record *scenario*; *before_stop* sees the live recording status before the stop."""
    base = e2e_env["base_url"]
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


def test_wheel_fault_run_names_order_level_and_mg_amplitudes_e2e(
    e2e_env: dict[str, str],
) -> None:
    run_id, insights = _record(e2e_env, "one-wheel-mild")
    try:
        diagnosis = insights["diagnosis"]
        assert diagnosis["verdict"] in {"fault", "weak_evidence"}, diagnosis
        assert diagnosis["source"] == "wheel/tire"
        assert diagnosis["order_code"] in {"T1", "T2"}
        assert diagnosis["confidence_level"] in {"strong", "moderate", "weak"}
        strongest = diagnosis["location_amplitudes"][0]
        assert strongest["amplitude_mg"] > 0
        assert strongest["ratio_to_strongest"] == 1.0
        assert strongest["db_above_floor"] is not None
        # One confidence expression only: levels, never percentages.
        for finding in insights["findings"]:
            assert finding["confidence_level"] in {"strong", "moderate", "weak"}
            assert "confidence_pct" not in finding
        pdf = pdf_text(wait_report_pdf_ready(e2e_env["base_url"], run_id).body)
        assert "likely cause" in pdf or "not enough evidence" in pdf
        assert "wheel" in pdf
    finally:
        _cleanup_run(e2e_env["base_url"], run_id)
        remove_all_clients(e2e_env["base_url"])


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
