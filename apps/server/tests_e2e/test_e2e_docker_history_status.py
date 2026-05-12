"""Docker E2E tests for history report and unknown-run states."""

from __future__ import annotations

import uuid

import pytest

from tests_e2e._docker_edge_helpers import (
    _cleanup_run,
    _simulate,
    _wait_complete,
)
from tests_e2e.e2e_helpers import (
    api_bytes,
    api_json,
    history_run_ids,
    wait_for,
)

pytestmark = pytest.mark.e2e


def test_report_and_insights_not_ready_states(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    run_id = str(api_json(base, "/api/recording/start", method="POST")["run_id"])
    try:
        _simulate(e2e_env, duration=3.0)
        insights_while = api_json(base, f"/api/history/{run_id}/insights", expected_status=422)
        assert "analysis" in str(insights_while.get("detail", "")).lower()

        pdf_while = api_bytes(base, f"/api/history/{run_id}/report.pdf", expected_status=422)
        assert b"analysis" in pdf_while.body.lower()

        api_json(base, "/api/recording/stop", method="POST")
        wait_for(
            lambda: run_id in history_run_ids(base),
            timeout_s=20,
            message=f"history/status run {run_id} did not appear",
        )
        complete = _wait_complete(base, run_id)
        assert complete["status"] == "complete", f"run {run_id} status: {complete['status']}"
        insights = api_json(base, f"/api/history/{run_id}/insights")
        assert insights.get("findings"), f"expected findings for run {run_id}"
    finally:
        api_json(base, "/api/recording/stop", method="POST")
        _cleanup_run(base, run_id)


def test_unknown_run_404_matrix(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    run_id = f"does-not-exist-{uuid.uuid4().hex}"
    api_json(base, f"/api/history/{run_id}", expected_status=404)
    api_json(base, f"/api/history/{run_id}/insights", expected_status=404)
    api_bytes(base, f"/api/history/{run_id}/report.pdf", expected_status=404)
    api_bytes(base, f"/api/history/{run_id}/export", expected_status=404)
    api_json(base, f"/api/history/{run_id}", method="DELETE", expected_status=404)
