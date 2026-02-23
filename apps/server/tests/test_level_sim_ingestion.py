# ruff: noqa: E501
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
import time
from pathlib import Path

import pytest
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]

# Default server settings (can be overridden via env vars for Docker)
BASE_URL = os.environ.get("VIBESENSOR_TEST_BASE_URL", "http://127.0.0.1:8000")
SIM_HOST = os.environ.get("VIBESENSOR_TEST_SIM_HOST", "127.0.0.1")
SIM_DATA_PORT = os.environ.get("VIBESENSOR_TEST_SIM_DATA_PORT", "5005")
SIM_CONTROL_PORT = os.environ.get("VIBESENSOR_TEST_SIM_CONTROL_PORT", "5006")


def _api_json(path: str, *, timeout: int = 30) -> dict:
    """Simple HTTP GET returning JSON."""
    from urllib.request import urlopen

    with urlopen(f"{BASE_URL}{path}", timeout=timeout) as resp:
        return json.loads(resp.read())


def _api_bytes(path: str, *, timeout: int = 30) -> bytes:
    """Simple HTTP GET returning raw bytes."""
    from urllib.request import urlopen

    with urlopen(f"{BASE_URL}{path}", timeout=timeout) as resp:
        return resp.read()


def _history_run_ids() -> set[str]:
    """Get current set of run IDs from history."""
    data = _api_json("/api/history")
    return {str(r["run_id"]) for r in data.get("runs", [])}


def _wait_for_analysis(run_id: str, *, timeout_s: float = 120.0) -> dict:
    """Poll until run reaches 'complete' status."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            data = _api_json(f"/api/history/{run_id}/insights")
            status = data.get("status", "")
            if status == "complete":
                return data
        except Exception:
            pass
        time.sleep(2.0)
    raise AssertionError(f"Run {run_id} did not complete within {timeout_s}s")


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

        # Record existing runs before simulation
        pre_runs = _history_run_ids()

        # Run the simulator for 20 seconds with 4 sensors
        sim_cmd = [
            sys.executable,
            "-m",
            "vibesensor_simulator.sim_sender",
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

        # Wait briefly for server to finalize the run
        time.sleep(3)

        # Find the new run ID
        post_runs = _history_run_ids()
        new_runs = post_runs - pre_runs
        assert len(new_runs) >= 1, (
            f"No new run appeared after simulation (pre={pre_runs}, post={post_runs})"
        )
        self.run_id = sorted(new_runs)[-1]  # Most recent

        # Wait for analysis to complete
        self.insights = _wait_for_analysis(self.run_id)

    def test_insights_has_required_fields(self) -> None:
        """Insights response has all required top-level fields."""
        for key in ("status", "top_causes", "findings", "speed_breakdown", "most_likely_origin"):
            assert key in self.insights, f"Missing '{key}' in insights"
        assert self.insights["status"] == "complete"

    def test_top_cause_exists(self) -> None:
        """At least one top cause should be present."""
        causes = self.insights.get("top_causes") or []
        assert len(causes) > 0, "No top causes in insights"
        top = causes[0]
        assert "source" in top, "Top cause missing 'source'"
        assert "confidence" in top, "Top cause missing 'confidence'"
        conf = float(top["confidence"])
        assert 0.0 <= conf <= 1.0, f"Confidence out of range: {conf}"
        src = str(top.get("source") or "").lower()
        assert "wheel" in src or "tire" in src, (
            f"Unexpected top source for one-wheel scenario: {src}"
        )
        strongest_location = str(top.get("strongest_location") or "").lower()
        assert "front-left" in strongest_location, (
            f"Expected front-left localization for injected fault, got {strongest_location!r}"
        )

    def test_findings_nonempty(self) -> None:
        """Findings list should be non-empty for a fault scenario."""
        findings = self.insights.get("findings") or []
        assert len(findings) > 0, "No findings in insights"

    def test_speed_breakdown_present(self) -> None:
        """Speed breakdown should be present and non-empty."""
        sb = self.insights.get("speed_breakdown") or []
        assert len(sb) > 0, "Speed breakdown is empty"

    def test_report_pdf_accessible(self) -> None:
        """PDF report should be downloadable and valid."""
        pdf_bytes = _api_bytes(f"/api/history/{self.run_id}/report.pdf")
        assert len(pdf_bytes) > 1000, f"PDF too small: {len(pdf_bytes)} bytes"
        assert pdf_bytes[:5] == b"%PDF-", "Not a valid PDF"
        reader = PdfReader(io.BytesIO(pdf_bytes))
        assert len(reader.pages) >= 2, f"PDF has only {len(reader.pages)} page(s)"
        pdf_text = "\n".join((page.extract_text() or "") for page in reader.pages).lower()
        for token in ("next steps", "evidence", "front-left"):
            assert token in pdf_text, f"Missing expected report content token: {token!r}"
