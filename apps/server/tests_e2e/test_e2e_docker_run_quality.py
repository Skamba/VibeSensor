"""Docker E2E tests for short-run edges plus one representative report-pipeline smoke."""

from __future__ import annotations

import pytest

from tests_e2e._docker_edge_helpers import (
    SHORT_RUN_DURATION_S,
    _assert_no_placeholders,
    _cleanup_clients,
    _cleanup_run,
    _run_status_context,
    _simulate,
    _wait_complete,
)
from tests_e2e.e2e_helpers import (
    api_json,
    history_run_ids,
    parse_export_zip,
    pdf_text,
    recording_status,
    wait_for,
    wait_for_stable,
    wait_export_ready,
    wait_report_pdf_ready,
)

pytestmark = pytest.mark.e2e


def test_no_data_or_short_run_behavior_e2e(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    _cleanup_clients(base)

    def _quiescence_state() -> dict[str, object]:
        status = recording_status(base)
        clients = api_json(base, "/api/clients").get("clients", [])
        return {
            "client_ids": [client.get("id") for client in clients],
            "run_id": status.get("run_id"),
            "analysis_in_progress": status.get("analysis_in_progress"),
            "last_completed_run_id": status.get("last_completed_run_id"),
        }

    def _quiescent_state() -> dict[str, object] | None:
        state = _quiescence_state()
        return state if not state["client_ids"] and state["run_id"] is None else None

    wait_for_stable(
        _quiescent_state,
        timeout_s=15.0,
        stable_for_s=2.5,
        interval_s=0.25,
        message="simulator clients or active recording did not stay quiescent before empty-run check",
        state=_quiescence_state,
    )
    before = history_run_ids(base)

    first = api_json(base, "/api/recording/start", method="POST")
    run_empty = str(first["run_id"])
    api_json(base, "/api/recording/stop", method="POST")
    after_empty = history_run_ids(base)
    assert run_empty not in after_empty
    assert after_empty == before

    second = api_json(base, "/api/recording/start", method="POST")
    run_short = str(second["run_id"])
    _simulate(e2e_env, duration=SHORT_RUN_DURATION_S)
    api_json(base, "/api/recording/stop", method="POST")

    wait_for(
        lambda: run_short in history_run_ids(base),
        timeout_s=20,
        message=f"short run {run_short} did not appear",
    )
    run = _wait_complete(base, run_short)
    assert run["status"] in {"complete", "error"}
    if run["status"] == "complete":
        pdf = wait_report_pdf_ready(base, run_short)
        assert pdf.body.startswith(b"%PDF-")
    _cleanup_run(base, run_short)


def test_representative_report_pipeline_smoke_e2e(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    run_id = str(api_json(base, "/api/recording/start", method="POST")["run_id"])
    try:
        # Keep the representative pipeline smoke fast by using a reduced-sensor capture
        # while still proving ingest -> diagnosis -> export -> PDF works end to end.
        _simulate(e2e_env, duration=3.0, count=2, names="front-left,rear-left")
        api_json(base, "/api/recording/stop", method="POST")
        run = _wait_complete(base, run_id)
        assert run["status"] == "complete", (
            f"reduced-sensor run not complete: {_run_status_context(run)}"
        )

        insights = api_json(base, f"/api/history/{run_id}/insights")
        assert insights.get("findings"), "reduced-sensor run produced no findings"

        export_resp = wait_export_ready(base, run_id)
        _, rows, _ = parse_export_zip(export_resp.body)
        assert rows, "reduced-sensor export has no rows"

        pdf_resp = wait_report_pdf_ready(base, run_id)
        text = pdf_text(pdf_resp.body)
        assert "vibesensor diagnostic report" in text
        _assert_no_placeholders(text)
    finally:
        api_json(base, "/api/recording/stop", method="POST")
        _cleanup_run(base, run_id)
