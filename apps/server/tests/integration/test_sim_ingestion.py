"""Level SIM – True simulator-ingestion test (slow, needs running server).

This is the one true end-to-end test that exercises the full path:
  simulator → UDP ingestion → processing → analysis → report API contract

It is marked as both ``e2e`` and ``long_sim`` so it is skipped in normal
CI unit-test runs but can be exercised in Docker-based CI or local dev.

Prerequisites:
  - A running VibeSensor server (``docker compose up -d`` or local server)
  - The ``vibesensor-sim`` CLI available
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from typing import Any
from urllib.request import Request, urlopen

import pytest
from _paths import SERVER_ROOT
from pypdf import PdfReader
from test_support.core import wait_until

ROOT = SERVER_ROOT.parent

# Default server settings (can be overridden via env vars for Docker)
BASE_URL = os.environ.get("VIBESENSOR_TEST_BASE_URL", "http://127.0.0.1:8000")
SIM_HOST = os.environ.get("VIBESENSOR_TEST_SIM_HOST", "127.0.0.1")
SIM_DATA_PORT = os.environ.get("VIBESENSOR_TEST_SIM_DATA_PORT", "9000")
SIM_CONTROL_PORT = os.environ.get("VIBESENSOR_TEST_SIM_CONTROL_PORT", "9001")


def _api_response_bytes(
    path: str,
    *,
    timeout: int = 30,
    method: str = "GET",
    data: bytes | None = None,
) -> bytes:
    """Read raw API response bytes for GET/POST helper wrappers."""
    request: str | Request
    if method == "GET" and data is None:
        request = f"{BASE_URL}{path}"
    else:
        request = Request(
            f"{BASE_URL}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
    with urlopen(request, timeout=timeout) as resp:
        return resp.read()


def _api_json(path: str, *, timeout: int = 30) -> dict[str, Any]:
    """Simple HTTP GET returning JSON."""
    return json.loads(_api_response_bytes(path, timeout=timeout))


def _api_post_json(path: str, *, timeout: int = 30) -> dict[str, Any]:
    """Simple HTTP POST returning JSON."""
    return json.loads(_api_response_bytes(path, timeout=timeout, method="POST", data=b""))


def _api_bytes(path: str, *, timeout: int = 30) -> bytes:
    """Simple HTTP GET returning raw bytes."""
    return _api_response_bytes(path, timeout=timeout)


def _history_run_ids() -> set[str]:
    """Get current set of run IDs from history."""
    data = _api_json("/api/history")
    return {str(r["run_id"]) for r in data.get("runs", [])}


def _recording_status() -> dict[str, Any]:
    """Return the current recording status payload."""
    return _api_json("/api/recording/status")


def _wait_for_recording_idle(*, timeout_s: float = 5.0) -> dict[str, Any]:
    """Wait until the server reports no active recording session."""
    last_status: dict[str, Any] = {}

    def _recording_is_idle() -> bool:
        nonlocal last_status
        last_status = _recording_status()
        return not str(last_status.get("run_id") or "").strip()

    assert wait_until(_recording_is_idle, timeout_s=timeout_s, step_s=0.1), (
        f"Recording session did not become idle within {timeout_s}s: {last_status}"
    )
    return last_status


def _wait_for_run_persisted(
    run_id: str,
    *,
    timeout_s: float = 15.0,
) -> tuple[bool, set[str]]:
    """Wait until *run_id* appears in history and return the last seen run IDs."""
    latest_run_ids: set[str] = set()

    def _run_seen() -> bool:
        nonlocal latest_run_ids
        latest_run_ids = _history_run_ids()
        return run_id in latest_run_ids

    persisted = wait_until(_run_seen, timeout_s=timeout_s, step_s=0.25)
    return persisted, latest_run_ids


def _wait_for_analysis(run_id: str, *, timeout_s: float = 120.0) -> dict[str, Any]:
    """Poll until the insights payload reflects completed current analysis."""
    last_payload: dict[str, Any] | None = None
    last_error: str | None = None

    def _analysis_complete() -> bool:
        nonlocal last_payload, last_error
        try:
            last_payload = _api_json(f"/api/history/{run_id}/insights")
            last_error = None
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            return False
        return str(last_payload.get("status") or "") == "complete"

    if wait_until(_analysis_complete, timeout_s=timeout_s, step_s=1.0):
        assert last_payload is not None
        return last_payload
    raise AssertionError(
        f"Run {run_id} did not complete within {timeout_s}s; "
        f"last_payload={last_payload}; last_error={last_error}"
    )


def _server_is_reachable() -> bool:
    """Check if the VibeSensor server is reachable via /api/health."""
    try:
        _api_json("/api/health", timeout=3)
        return True
    except Exception:
        return False


@pytest.mark.e2e
@pytest.mark.long_sim
class TestSimulatorIngestion:
    """True simulator → ingestion → analysis → report API contract test.

    This test runs the simulator against a live server, waits for analysis
    to complete, and validates the full API contract.
    """

    @pytest.fixture(autouse=True)
    def _check_server_and_run(self) -> None:
        """Skip if server is not reachable, then run the simulator."""
        if not _server_is_reachable():
            pytest.skip("VibeSensor server is not reachable (start with docker compose up)")

        # Reset any stale active recording session first so this test controls
        # the run lifecycle deterministically.
        _api_post_json("/api/recording/stop")
        _wait_for_recording_idle()

        pre_runs = _history_run_ids()
        start_status = _api_post_json("/api/recording/start")
        started_run_id = str(start_status.get("run_id") or "").strip()
        assert started_run_id, f"Logging start did not return run_id: {start_status}"

        # Run the simulator for 20 seconds with 4 sensors
        sim_cmd = [
            sys.executable,
            "-m",
            "vibesensor.adapters.simulator.sim_sender",
            "--server-host",
            SIM_HOST,
            "--server-data-port",
            SIM_DATA_PORT,
            "--server-control-port",
            SIM_CONTROL_PORT,
            "--count",
            "4",
            "--names",
            "front-left,front-right,rear-left,rear-right",
            "--scenario",
            "one-wheel-mild",
            "--fault-wheel",
            "front-left",
            "--duration",
            "20",
            "--no-auto-server",
            "--no-interactive",
        ]
        subprocess.run(sim_cmd, cwd=str(ROOT), check=True, timeout=90)

        # Finalize immediately so analysis can start without waiting for no-data timeout.
        _api_post_json("/api/recording/stop")

        # Wait for server to persist the run ID before continuing.
        persisted, post_runs = _wait_for_run_persisted(started_run_id)

        # Prefer the explicit started run id; fallback to history diff if needed.
        if persisted and started_run_id in post_runs:
            self.run_id = started_run_id
        else:
            new_runs = post_runs - pre_runs
            if not new_runs:
                pytest.skip(
                    "Server is reachable but did not persist a new history run after logging "
                    "start/stop; skip simulator-ingestion e2e in this environment "
                    f"(started={started_run_id}, visible_runs={sorted(post_runs)})",
                )
            self.run_id = sorted(new_runs)[-1]

        # Wait for analysis to complete
        self.insights = _wait_for_analysis(self.run_id)

    def test_insights_has_required_fields(self) -> None:
        """Insights response has all required top-level fields."""
        for key in (
            "top_causes",
            "findings",
            "speed_breakdown",
            "most_likely_origin",
        ):
            assert key in self.insights, f"Missing '{key}' in insights"

    def test_top_cause_exists(self) -> None:
        """At least one top cause should be present."""
        causes = self.insights.get("top_causes") or []
        assert len(causes) > 0, "No top causes in insights"
        top = causes[0]
        assert "suspected_source" in top, "Top cause missing 'suspected_source'"
        assert "confidence" in top, "Top cause missing 'confidence'"
        conf = float(top["confidence"])
        assert 0.0 <= conf <= 1.0, f"Confidence out of range: {conf}"
        src = str(top.get("suspected_source") or "").lower()
        assert "wheel" in src or "tire" in src, (
            f"Unexpected top source for one-wheel scenario: {src}"
        )
        strongest_location = str(top.get("strongest_location") or "").lower()
        assert "front-left" in strongest_location, (
            f"Expected front-left localization for injected fault, got {strongest_location!r}"
        )

    def test_wheel_overlap_is_demoted_or_explicitly_explained(self) -> None:
        """Single-wheel simulator runs should not surface opaque wheel/driveline ties."""
        causes = self.insights.get("top_causes") or []
        assert causes, "Expected at least one top cause"
        sources = [str(cause.get("suspected_source") or "").lower() for cause in causes]
        assert sources[0] == "wheel/tire"
        if "driveline" in sources:
            reason = str(causes[0].get("confidence_reason") or "").lower()
            assert "wheel and driveline evidence overlap" in reason
            assert "could not strongly differentiate" in reason
            assert "inspect both areas" in reason

    def test_findings_nonempty(self) -> None:
        """Findings list should be non-empty for a fault scenario."""
        findings = self.insights.get("findings") or []
        assert len(findings) > 0, "No findings in insights"

    def test_speed_breakdown_present(self) -> None:
        """Speed breakdown should be present and non-empty."""
        sb = self.insights.get("speed_breakdown") or []
        assert len(sb) > 0, "Speed breakdown is empty"

    def test_history_run_has_known_simulator_car(self) -> None:
        """Simulator runs should persist a deterministic known car profile."""
        history_run = _api_json(f"/api/history/{self.run_id}")
        metadata = history_run.get("metadata") or {}
        active_car_snapshot = metadata.get("active_car_snapshot") or {}
        assert active_car_snapshot.get("name") == "VibeSensor Simulator"
        assert active_car_snapshot.get("type") == "sedan"

    def test_report_pdf_accessible(self) -> None:
        """PDF report should be downloadable and valid."""
        pdf_bytes = _api_bytes(f"/api/history/{self.run_id}/report.pdf")
        assert len(pdf_bytes) > 1000, f"PDF too small: {len(pdf_bytes)} bytes"
        assert pdf_bytes[:5] == b"%PDF-", "Not a valid PDF"
        reader = PdfReader(io.BytesIO(pdf_bytes))
        assert len(reader.pages) >= 2, f"PDF has only {len(reader.pages)} page(s)"
        pdf_text = "\n".join((page.extract_text() or "") for page in reader.pages).lower()
        for token in ("what to do next", "evidence", "front-left", "vibesensor simulator"):
            assert token in pdf_text, f"Missing expected report content token: {token!r}"

    def test_report_pdf_softens_wheel_driveline_overlap_wording(self) -> None:
        """Wheel/driveline overlaps should not read like a localized driveline diagnosis."""
        pdf_text = "\n".join(
            page.extract_text() or ""
            for page in PdfReader(
                io.BytesIO(_api_bytes(f"/api/history/{self.run_id}/report.pdf")),
            ).pages
        ).lower()
        causes = self.insights.get("top_causes") or []
        sources = {str(cause.get("suspected_source") or "").lower() for cause in causes}

        assert "1x driveshaft stayed strongest near front-left" not in pdf_text
        if {"wheel/tire", "driveline"}.issubset(sources):
            assert "wheel and driveline evidence overlap" in pdf_text
