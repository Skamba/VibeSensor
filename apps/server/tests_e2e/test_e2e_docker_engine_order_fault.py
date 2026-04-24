"""Docker E2E test for full-stack engine-order diagnosis."""

from __future__ import annotations

import os
import re
import time

import pytest

from tests_e2e._docker_edge_helpers import (
    _cleanup_clients,
    _cleanup_run,
    _prepare_simulator_locations,
)
from tests_e2e.e2e_helpers import (
    api_bytes,
    api_json,
    history_run_ids,
    non_ref_findings,
    parse_export_zip,
    pdf_text,
    run_cleanup_steps,
    run_simulator,
    wait_for,
    wait_run_status,
)

pytestmark = pytest.mark.e2e


def test_e2e_docker_engine_order_fault() -> None:
    base_url = os.environ["VIBESENSOR_BASE_URL"]
    sim_host = os.environ["VIBESENSOR_SIM_SERVER_HOST"]
    sim_data_port = os.environ["VIBESENSOR_SIM_DATA_PORT"]
    sim_control_port = os.environ["VIBESENSOR_SIM_CONTROL_PORT"]
    sim_duration = os.environ["VIBESENSOR_SIM_DURATION"]
    e2e_env = {
        "base_url": base_url,
        "sim_host": sim_host,
        "sim_data_port": sim_data_port,
        "sim_control_port": sim_control_port,
        "sim_duration": sim_duration,
    }
    run_id: str | None = None
    _cleanup_clients(base_url)
    wait_for(
        lambda: not api_json(base_url, "/api/clients").get("clients"),
        timeout_s=5.0,
        interval_s=0.5,
        message="simulator clients did not quiesce before engine-order E2E run",
    )
    time.sleep(2.5)
    _prepare_simulator_locations(e2e_env)
    try:
        api_json(
            base_url,
            "/api/settings/speed-source",
            method="PUT",
            body={"speed_source": "manual", "manual_speed_kph": 100.0},
        )
        start = api_json(base_url, "/api/recording/start", method="POST")
        assert start["enabled"] is True
        run_id = str(start["run_id"])
        run_simulator(
            base_url=base_url,
            sim_host=sim_host,
            sim_data_port=sim_data_port,
            sim_control_port=sim_control_port,
            duration_s=float(sim_duration),
            count=4,
            scenario="engine-order",
        )

        api_json(base_url, "/api/recording/stop", method="POST")
        wait_for(
            lambda: run_id if run_id in history_run_ids(base_url) else None,
            timeout_s=10.0,
            interval_s=0.5,
            message=f"Run {run_id} did not become visible in history",
        )
        wait_run_status(base_url, run_id, timeout_s=90.0)

        insights = api_json(base_url, f"/api/history/{run_id}/insights")
        findings = non_ref_findings(insights)
        assert findings, "Expected non-reference findings for engine-order scenario"

        primary = findings[0]
        assert primary.get("suspected_source") == "engine"
        frequency_label = str(primary.get("frequency_hz_or_order") or "").lower()
        assert "engine" in frequency_label

        top_causes = [item for item in insights.get("top_causes", []) if isinstance(item, dict)]
        assert top_causes, "Expected ranked top causes for engine-order scenario"
        assert top_causes[0].get("suspected_source") == "engine"

        run_payload = api_json(base_url, f"/api/history/{run_id}")
        run_analysis = run_payload.get("analysis") or {}
        analysis_findings = non_ref_findings(run_analysis)
        assert analysis_findings, "Expected non-reference findings in run analysis"
        assert analysis_findings[0].get("suspected_source") == "engine"

        export_resp = api_bytes(base_url, f"/api/history/{run_id}/export")
        assert str(export_resp.headers.get("content-type", "")).startswith("application/zip")
        _, rows, names = parse_export_zip(export_resp.body)
        assert names == {f"{run_id}.json", f"{run_id}_raw.csv"}
        assert rows, "Expected raw export rows for engine-order scenario"

        pdf_resp = api_bytes(base_url, f"/api/history/{run_id}/report.pdf?lang=en")
        assert str(pdf_resp.headers.get("content-type", "")).startswith("application/pdf")
        assert pdf_resp.body[:5] == b"%PDF-"
        report_text = pdf_text(pdf_resp.body)
        assert "what to do next" in report_text
        assert "recapture before acting" in report_text
        assert re.search(r"(?:most\s+)?likely source\s+insufficient evidence", report_text)
        assert not re.search(r"(?:most\s+)?likely source\s+wheel / tire", report_text)
    finally:
        cleanup_steps = [
            ("stop recording", lambda: api_json(base_url, "/api/recording/stop", method="POST")),
            ("cleanup simulator clients", lambda: _cleanup_clients(base_url)),
        ]
        if run_id is not None:
            cleanup_steps.insert(1, ("cleanup run", lambda rid=run_id: _cleanup_run(base_url, rid)))
        run_cleanup_steps(*cleanup_steps)
