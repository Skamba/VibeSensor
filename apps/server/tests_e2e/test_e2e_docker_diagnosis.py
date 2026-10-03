"""Docker E2E: a recorded run's persisted diagnosis names the verdict the UI and PDF show."""

from __future__ import annotations

import pytest

from tests_e2e._docker_edge_helpers import _cleanup_run, _wait_complete
from tests_e2e.e2e_helpers import api_json, remove_all_clients, run_simulator

pytestmark = pytest.mark.e2e

# Covers the first clock-sync exchanges plus several analysis windows at speed.
_SIM_DURATION_S = 18.0


def _record(e2e_env: dict[str, str], scenario: str) -> tuple[str, dict]:
    base = e2e_env["base_url"]
    remove_all_clients(base)
    run_id = str(api_json(base, "/api/recording/start", method="POST")["run_id"])
    run_simulator(
        base_url=base,
        sim_host=e2e_env["sim_host"],
        sim_data_port=e2e_env["sim_data_port"],
        sim_control_port=e2e_env["sim_control_port"],
        client_control_base=e2e_env["sim_client_control_base"],
        duration_s=_SIM_DURATION_S,
        count=4,
        scenario=scenario,
        fault_wheel="rear-left",
        speed_kmh=80.0,
    )
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
    finally:
        _cleanup_run(e2e_env["base_url"], run_id)
        remove_all_clients(e2e_env["base_url"])
