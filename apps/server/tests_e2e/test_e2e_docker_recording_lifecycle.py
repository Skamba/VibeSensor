"""Docker E2E tests for recording lifecycle edge cases."""

from __future__ import annotations

import pytest

from tests_e2e._docker_edge_helpers import (
    _cleanup_run,
    _simulate,
    _wait_complete,
)
from tests_e2e.e2e_helpers import (
    CAPPED_RECORDING_S,
    api_json,
    history_run_ids,
    registered_client_ids,
    sim_client_ids,
    wait_for,
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
