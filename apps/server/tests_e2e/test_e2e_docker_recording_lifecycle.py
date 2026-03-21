"""Docker E2E tests for recording lifecycle edge cases."""

from __future__ import annotations

import pytest

from tests_e2e._docker_edge_helpers import (
    _cleanup_run,
    _simulate,
    _wait_complete,
)
from tests_e2e.e2e_helpers import (
    api_json,
    history_run_ids,
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
            lambda: api_json(base, "/api/clients").get("clients") or None,
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

        _simulate(e2e_env, duration=3.0)
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
            lambda: api_json(base, "/api/clients").get("clients") or None,
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
