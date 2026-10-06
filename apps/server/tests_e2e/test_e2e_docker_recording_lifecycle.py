"""Docker E2E tests for recording lifecycle edge cases."""

from __future__ import annotations

import threading

import pytest

from tests_e2e._docker_edge_helpers import (
    _cleanup_run,
    _simulate,
    _wait_complete,
)
from tests_e2e.conftest import PowerCut
from tests_e2e.e2e_helpers import (
    CAPPED_RECORDING_S,
    api_json,
    history_run_ids,
    pdf_text,
    registered_client_ids,
    remove_all_clients,
    run_simulator,
    sim_client_ids,
    wait_for,
    wait_report_pdf_ready,
    wait_run_status,
)

pytestmark = pytest.mark.e2e


def test_logging_start_while_recording_rollover(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    run_ids: list[str] = []
    try:
        first = api_json(base, "/api/recording/start", method="POST")
        run_1 = str(first["run_id"])
        run_ids.append(run_1)
        _simulate(e2e_env, duration=8.0)
        wait_for(
            lambda: registered_client_ids(base) >= set(sim_client_ids(4)) or None,
            timeout_s=15.0,
            message="rollover test did not observe live clients before second start",
        )

        second = api_json(base, "/api/recording/start", method="POST")
        run_2 = str(second["run_id"])
        run_ids.append(run_2)
        assert run_2 != run_1

        wait_for(
            lambda: (
                run
                if (run := api_json(base, f"/api/history/{run_1}", expected_status=(200, 404))).get(
                    "status"
                )
                in {"analyzing", "complete", "error"}
                else None
            ),
            timeout_s=30,
            message=f"first rollover run {run_1} did not finalize",
        )

        _simulate(e2e_env)
        api_json(base, "/api/recording/stop", method="POST")

        final_1 = _wait_complete(base, run_1)
        final_2 = _wait_complete(base, run_2)
        assert final_1["status"] == "complete", f"rollover run_1 status: {final_1['status']}"
        assert final_2["status"] == "complete", f"rollover run_2 status: {final_2['status']}"

        for run_id in (run_1, run_2):
            insights = api_json(base, f"/api/history/{run_id}/insights")
            assert insights.get("findings"), f"expected findings for rollover run {run_id}"
    finally:
        api_json(base, "/api/recording/stop", method="POST", expected_status=(200,))
        for run_id in run_ids:
            _cleanup_run(base, run_id)


def test_readiness_never_waits_on_speed_and_names_what_a_typed_in_speed_can_test_e2e(
    e2e_env: dict[str, str],
) -> None:
    """Start is gated only on sensors, car and speed source; a steady speed is advice.

    The simulator types in its speed (a manual override), so readiness must say
    the run can test nothing for sure (docs/run_lifecycle.md, "capabilities").
    """
    base = e2e_env["base_url"]
    remove_all_clients(base)
    (sensor_id,) = sim_client_ids(1)
    simulator = threading.Thread(
        target=run_simulator,
        kwargs={
            "base_url": base,
            "sim_host": e2e_env["sim_host"],
            "sim_data_port": e2e_env["sim_data_port"],
            "sim_control_port": e2e_env["sim_control_port"],
            # A typed-in speed: the run can test nothing for sure.
            "gps_port": None,
            "duration_s": 14.0,
            "count": 1,
            "names": "front-left",
            "speed_kmh": 80.0,
        },
    )
    simulator.start()
    seen: list[dict] = []
    try:
        wait_for(
            lambda: sensor_id in registered_client_ids(base) or None,
            timeout_s=10.0,
            message="simulated sensor never registered",
        )
        api_json(
            base,
            f"/api/clients/{sensor_id}/location",
            method="POST",
            body={"location_code": "front_left_wheel"},
        )

        def ready() -> dict | None:
            readiness = api_json(base, "/api/recording/status")["capture_readiness"]
            seen.append(readiness)
            return readiness if readiness["is_ready"] else None

        readiness = wait_for(ready, timeout_s=10.0, message="readiness never became ready")
        assert readiness["capabilities"] == {
            "wheel": "manual_speed",
            "driveline": "manual_speed",
            "engine": "manual_speed",
        }, readiness
        speed_states = {
            check["state"]
            for snapshot in seen
            for check in snapshot["checks"]
            if check["check_key"] == "speed_stable"
        }
        assert "fail" not in speed_states, seen
    finally:
        simulator.join()
        remove_all_clients(base)


def test_logging_stop_when_idle_noop(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    before = history_run_ids(base)
    stopped = api_json(base, "/api/recording/stop", method="POST")
    assert stopped["enabled"] is False, "stop-when-idle should report enabled=False"
    assert stopped["run_id"] is None, "stop-when-idle should report run_id=None"
    assert history_run_ids(base) == before, "stop-when-idle should not create a run"


def test_delete_active_run_returns_409_e2e(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    run_id = ""
    try:
        run_id = str(api_json(base, "/api/recording/start", method="POST")["run_id"])
        _simulate(e2e_env, duration=5.0)
        wait_for(
            lambda: registered_client_ids(base) >= set(sim_client_ids(4)) or None,
            timeout_s=15.0,
            message="active-run delete test did not observe live clients",
        )
        wait_for(
            lambda: (
                run
                if (
                    run := api_json(base, f"/api/history/{run_id}", expected_status=(200, 404))
                ).get("run_id")
                == run_id
                else None
            ),
            timeout_s=30,
            message=f"active run {run_id} did not materialize in history",
        )
        err = api_json(base, f"/api/history/{run_id}", method="DELETE", expected_status=409)
        assert "active run" in str(err.get("detail", "")).lower()
    finally:
        api_json(base, "/api/recording/stop", method="POST")
        if run_id:
            _wait_complete(base, run_id)
            _cleanup_run(base, run_id)


def test_recording_auto_stops_at_the_configured_cap_e2e(capped_e2e_env: dict[str, str]) -> None:
    """The recording cap (30 min on a car) stops the run and still yields a full analysis."""
    base = capped_e2e_env["base_url"]
    run_id = str(api_json(base, "/api/recording/start", method="POST")["run_id"])
    try:
        # Keep streaming well past the cap, as a driver who forgot to stop would.
        _simulate(capped_e2e_env, duration=CAPPED_RECORDING_S + 6.0)
        status = api_json(base, "/api/recording/status")
        assert status["enabled"] is False, status
        assert status["last_stop_reason"] == "max_duration", status

        run = _wait_complete(base, run_id)
        assert run["status"] == "complete", run
        # Data streamed after the cap never reaches the run.
        assert history_run_ids(base) == {run_id}
        analysis = api_json(base, f"/api/history/{run_id}")["analysis"]
        assert CAPPED_RECORDING_S - 1.0 <= analysis["duration_s"] <= CAPPED_RECORDING_S + 1.5
        metadata = analysis["analysis_metadata"]
        assert metadata["raw_capture_mode"] in {"raw_backed", "partial_raw_backed"}
        assert metadata["raw_backed_sample_count"] > 0
        assert analysis["diagnosis"]["verdict"] in {"fault", "weak_evidence", "no_fault"}
    finally:
        _cleanup_run(base, run_id)


def test_a_recording_cut_off_by_a_power_loss_is_analysed_after_the_restart(
    power_cut: PowerCut,
) -> None:
    base = power_cut.env["base_url"]
    run_id = str(api_json(base, "/api/recording/start", method="POST")["run_id"])
    _simulate(power_cut.env)
    # The power goes while the run is still recording: no Stop, no shutdown.
    power_cut.cut_and_restore()

    run = wait_run_status(base, run_id, statuses=("complete", "error"), timeout_s=60.0)
    assert run["status"] == "complete", run.get("error_message")
    assert run["metadata"]["interrupted"] is True
    assert {row["run_id"]: row["interrupted"] for row in api_json(base, "/api/history")["runs"]}[
        run_id
    ]
    analysis = run["analysis"]
    assert "recording_interrupted" in {warning["code"] for warning in analysis["warnings"]}
    assert analysis["analysis_metadata"]["raw_backed_sample_count"] > 0
    pdf = " ".join(pdf_text(wait_report_pdf_ready(base, run_id).body).split())
    assert "power was lost" in pdf, pdf[:600]
