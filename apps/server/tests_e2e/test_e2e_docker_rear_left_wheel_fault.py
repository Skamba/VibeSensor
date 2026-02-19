from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pytest
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.e2e


def _api(base_url: str, path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = Request(f"{base_url}{path}", data=data, method=method, headers=headers)
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _api_bytes(base_url: str, path: str) -> tuple[bytes, str]:
    req = Request(f"{base_url}{path}")
    with urlopen(req, timeout=30) as resp:
        return resp.read(), str(resp.headers.get("Content-Type", ""))


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(filter(None, (page.extract_text() for page in reader.pages))).lower()


def test_e2e_docker_rear_left_wheel_fault() -> None:
    base_url = os.environ["VIBESENSOR_BASE_URL"]
    sim_host = os.environ["VIBESENSOR_SIM_SERVER_HOST"]
    sim_data_port = os.environ["VIBESENSOR_SIM_DATA_PORT"]
    sim_control_port = os.environ["VIBESENSOR_SIM_CONTROL_PORT"]
    sim_duration = os.environ["VIBESENSOR_SIM_DURATION"]
    sim_log_path = Path(os.environ["VIBESENSOR_SIM_LOG"])

    history_before = _api(base_url, "/api/history")
    assert history_before["runs"] == [], "Expected empty history before E2E run"

    _api(base_url, "/api/speed-override", method="POST", body={"speed_kmh": 100.0})
    start = _api(base_url, "/api/logging/start", method="POST")
    assert start["enabled"] is True

    sim_cmd = [
        sys.executable,
        str(ROOT / "apps" / "simulator" / "sim_sender.py"),
        "--server-host",
        sim_host,
        "--server-data-port",
        sim_data_port,
        "--server-control-port",
        sim_control_port,
        "--server-http-port",
        base_url.rsplit(":", 1)[-1],
        "--count",
        "4",
        "--names",
        "front-left,front-right,rear-left,rear-right",
        "--scenario",
        "one-wheel-mild",
        "--fault-wheel",
        "rear-left",
        "--speed-kmh",
        "0",
        "--duration",
        sim_duration,
        "--no-auto-server",
        "--no-interactive",
    ]
    with sim_log_path.open("w", encoding="utf-8") as sim_log:
        subprocess.run(sim_cmd, cwd=str(ROOT), check=True, stdout=sim_log, stderr=subprocess.STDOUT)

    _api(base_url, "/api/logging/stop", method="POST")

    deadline = time.monotonic() + 40.0
    run_id = None
    while time.monotonic() < deadline:
        history_after = _api(base_url, "/api/history")
        if len(history_after["runs"]) == 1 and history_after["runs"][0]["status"] == "complete":
            run_id = str(history_after["runs"][0]["run_id"])
            break
        time.sleep(1.0)
    assert run_id is not None, "Run did not complete in time"

    insights = _api(base_url, f"/api/history/{run_id}/insights")
    findings = [
        f
        for f in insights.get("findings", [])
        if not str(f.get("finding_id", "")).startswith("REF_")
    ]
    assert findings, "Expected non-reference findings"

    primary = findings[0]
    assert primary.get("suspected_source") == "wheel/tire"
    primary_location = str(primary.get("strongest_location") or "").lower()
    assert "rear left" in primary_location or "rear-left" in primary_location
    top_causes = [item for item in insights.get("top_causes", []) if isinstance(item, dict)]
    assert top_causes, "Expected ranked top causes"
    assert top_causes[0].get("source") == "wheel/tire"

    pdf_bytes, content_type = _api_bytes(base_url, f"/api/history/{run_id}/report.pdf?lang=en")
    assert content_type.startswith("application/pdf")
    assert pdf_bytes[:5] == b"%PDF-"
    pdf_text = _pdf_text(pdf_bytes)
    assert "primary finding:" in pdf_text
    assert "wheel / tire" in pdf_text
    assert "rear left" in pdf_text or "rear-left" in pdf_text
    assert "primary finding: driveline" not in pdf_text
    assert "primary finding: engine" not in pdf_text
