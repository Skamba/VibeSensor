"""Black-box simulated-run tests for the VibeSensor history feature.

Each test boots the real VibeSensor server, sends real UDP sensor data using
the simulator infrastructure (``SimClient``/``make_frame``/``pack_data``), then
verifies that the full ingestion → SQLite persistence → post-stop analysis →
history API pipeline produces correct vibration findings.

Default tests (~20 s each) are unmarked.  Longer stress tests carry the
``long_sim`` marker and can be run separately with ``pytest -m long_sim``.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pi"))
sys.path.insert(0, str(ROOT / "tools" / "simulator"))

from sim_sender import (  # noqa: E402
    SimClient,
    apply_one_wheel_mild_scenario,
    make_client_id,
)

from vibesensor.protocol import pack_data, pack_hello  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SENSOR_NAMES = [
    "Front Left Wheel",
    "Front Right Wheel",
    "Rear Left Wheel",
    "Rear Right Wheel",
]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _write_temp_config(tmp_path: Path, http_port: int, udp_data: int, udp_ctrl: int) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"""\
server:
  host: "127.0.0.1"
  port: {http_port}
udp:
  data_listen: "127.0.0.1:{udp_data}"
  control_listen: "127.0.0.1:{udp_ctrl}"
logging:
  log_metrics: false
  metrics_log_path: "{tmp_path}/metrics.jsonl"
  metrics_log_hz: 4
  sensor_model: ADXL345
  history_db_path: "{tmp_path}/history.db"
storage:
  clients_json_path: "{tmp_path}/clients.json"
gps:
  gps_enabled: false
""",
        encoding="utf-8",
    )
    return cfg


def _api(base: str, path: str, method: str = "GET", body: dict | None = None) -> Any:
    url = f"{base}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"} if body else {}
    req = Request(url, data=data, method=method, headers=headers)
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _api_bytes(base: str, path: str) -> tuple[bytes, str]:
    """Fetch raw bytes from an endpoint.  Returns (content, content_type)."""
    url = f"{base}{path}"
    req = Request(url)
    with urlopen(req, timeout=30) as resp:
        ct = resp.headers.get("Content-Type", "")
        return resp.read(), ct


def _pdf_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF as a single lowercased string."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    return "\n".join(parts).lower()


def _wait_health(base: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            _api(base, "/api/health")
            return
        except (URLError, OSError, TimeoutError):
            time.sleep(0.3)
    raise TimeoutError(f"Server at {base} did not become healthy within {timeout}s")


# ---------------------------------------------------------------------------
# Server + simulator lifecycle
# ---------------------------------------------------------------------------


def _build_clients(
    names: list[str],
    *,
    server_host: str,
    server_data_port: int,
    server_control_port: int,
    sample_rate_hz: int = 800,
    frame_samples: int = 200,
    profile_name: str = "engine_idle",
    control_base: int = 0,
) -> list[SimClient]:
    clients: list[SimClient] = []
    for i, name in enumerate(names):
        ctrl_port = control_base + i if control_base else _free_port()
        clients.append(
            SimClient(
                name=name,
                client_id=make_client_id(i + 1),
                control_port=ctrl_port,
                sample_rate_hz=sample_rate_hz,
                frame_samples=frame_samples,
                server_host=server_host,
                server_data_port=server_data_port,
                server_control_port=server_control_port,
                profile_name=profile_name,
            )
        )
    return clients


async def _send_hello(sim: SimClient) -> None:
    """Send a single hello packet so the server registers the client."""
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol,
        local_addr=("127.0.0.1", 0),
    )
    try:
        pkt = pack_hello(
            client_id=sim.client_id,
            control_port=sim.control_port,
            sample_rate_hz=sim.sample_rate_hz,
            name=sim.name,
            firmware_version="sim-test",
        )
        transport.sendto(pkt, (sim.server_host, sim.server_control_port))
    finally:
        transport.close()


async def _send_data(sim: SimClient, server_data_port: int) -> None:
    """Generate one frame of raw sensor data and send it via UDP."""
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol,
        local_addr=("127.0.0.1", 0),
    )
    try:
        samples = sim.make_frame()
        pkt = pack_data(
            client_id=sim.client_id,
            seq=sim.seq,
            t0_us=time.monotonic_ns() // 1000,
            samples=samples,
        )
        transport.sendto(pkt, (sim.server_host, server_data_port))
        sim.seq = (sim.seq + 1) & 0xFFFFFFFF
    finally:
        transport.close()


async def _run_sim_session(
    clients: list[SimClient],
    server_data_port: int,
    duration_s: float = 20.0,
    frame_hz: float = 4.0,
) -> None:
    """Stream data from all simulated clients for *duration_s* seconds."""
    # Initial hello burst so server knows all clients
    for sim in clients:
        await _send_hello(sim)
    await asyncio.sleep(0.5)
    for sim in clients:
        await _send_hello(sim)
    await asyncio.sleep(0.3)

    frame_period = 1.0 / frame_hz
    end = asyncio.get_event_loop().time() + duration_s
    hello_counter = 0
    while asyncio.get_event_loop().time() < end:
        for sim in clients:
            await _send_data(sim, server_data_port)
        hello_counter += 1
        if hello_counter % int(frame_hz * 2) == 0:
            for sim in clients:
                await _send_hello(sim)
        await asyncio.sleep(frame_period)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _ServerHandle:
    """Wraps a running VibeSensor server for testing."""

    def __init__(
        self,
        tmp_path: Path,
        http_port: int,
        udp_data_port: int,
        udp_ctrl_port: int,
    ):
        self.tmp_path = tmp_path
        self.http_port = http_port
        self.udp_data_port = udp_data_port
        self.udp_ctrl_port = udp_ctrl_port
        self.base_url = f"http://127.0.0.1:{http_port}"
        self.proc: Any = None

    def api(self, path: str, method: str = "GET", body: dict | None = None) -> Any:
        return _api(self.base_url, path, method=method, body=body)

    def api_bytes(self, path: str) -> tuple[bytes, str]:
        return _api_bytes(self.base_url, path)


@pytest.fixture()
def server(tmp_path):
    """Start a real VibeSensor server in a subprocess and yield a handle."""
    http_port = _free_port()
    udp_data = _free_port()
    udp_ctrl = _free_port()
    cfg = _write_temp_config(tmp_path, http_port, udp_data, udp_ctrl)

    # Prevent the subprocess from serving static files (no UI build needed)
    env = {**os.environ, "VIBESENSOR_SERVE_STATIC": "0"}
    import subprocess

    proc = subprocess.Popen(
        [sys.executable, "-m", "vibesensor.app", "--config", str(cfg)],
        cwd=str(ROOT / "pi"),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    handle = _ServerHandle(tmp_path, http_port, udp_data, udp_ctrl)
    handle.proc = proc
    try:
        _wait_health(handle.base_url, timeout=15)
        yield handle
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)


# ---------------------------------------------------------------------------
# Default tests (~20 s each, included in normal CI)
# ---------------------------------------------------------------------------


def test_sim_wheel_imbalance_front_left(server: _ServerHandle) -> None:
    """Wheel-imbalance profile on front-left; other sensors quiet.

    Verifies that stop triggers analysis, history lists the run, and
    analysis finds a wheel-related vibration sourced at the front-left.
    """
    clients = _build_clients(
        _SENSOR_NAMES,
        server_host="127.0.0.1",
        server_data_port=server.udp_data_port,
        server_control_port=server.udp_ctrl_port,
    )
    # Strong wheel_imbalance on front-left, quiet elsewhere
    for c in clients:
        if c.name == "Front Left Wheel":
            c.profile_name = "wheel_imbalance"
            c.amp_scale = 1.0
            c.noise_scale = 1.0
        else:
            c.profile_name = "engine_idle"
            c.amp_scale = 0.05
            c.noise_scale = 0.6

    # Set speed override
    server.api("/api/speed-override", method="POST", body={"speed_kmh": 100.0})

    # Start recording
    status = server.api("/api/logging/start", method="POST")
    assert status["enabled"] is True

    # Stream sensor data for ~20 s
    asyncio.run(_run_sim_session(clients, server.udp_data_port, duration_s=20.0))

    # Stop recording → triggers analysis
    server.api("/api/logging/stop", method="POST")

    # Allow a moment for post-analysis to complete
    time.sleep(2.0)

    # Verify history lists the run
    history = server.api("/api/history")
    runs = history["runs"]
    assert len(runs) >= 1
    run = runs[0]
    assert run["status"] == "complete", f"Run status: {run['status']}"
    assert run["sample_count"] > 0

    # Verify analysis insights
    insights = server.api(f"/api/history/{run['run_id']}/insights")
    assert "findings" in insights
    findings = insights["findings"]

    # At least one finding should mention wheel
    wheel_findings = [f for f in findings if "wheel" in str(f.get("suspected_source", "")).lower()]
    assert len(wheel_findings) > 0, (
        f"Expected wheel finding; got sources: {[f.get('suspected_source') for f in findings]}"
    )

    # Verify PDF report can be generated from the stored analysis
    pdf_bytes, content_type = server.api_bytes(f"/api/history/{run['run_id']}/report.pdf?lang=en")
    assert content_type == "application/pdf"
    assert len(pdf_bytes) > 500, f"PDF too small: {len(pdf_bytes)} bytes"
    assert pdf_bytes[:5] == b"%PDF-", "Response is not a valid PDF"

    # Verify PDF contains the expected analysis content
    text = _pdf_text(pdf_bytes)
    assert "vibesensor" in text, "PDF missing VibeSensor branding"
    assert "wheel" in text, "PDF should mention wheel findings"
    # The run used 4 sensor locations — the PDF should reference sensor data
    assert "front left" in text or "front-left" in text, "PDF should mention Front Left sensor"


def test_sim_one_wheel_mild_front_right(server: _ServerHandle) -> None:
    """Uses the simulator's ``apply_one_wheel_mild_scenario`` for front-right.

    This is the exact scenario the existing sim_sender supports.
    """
    clients = _build_clients(
        ["front-left", "front-right", "rear-left", "rear-right"],
        server_host="127.0.0.1",
        server_data_port=server.udp_data_port,
        server_control_port=server.udp_ctrl_port,
    )
    apply_one_wheel_mild_scenario(clients, "front-right")

    server.api("/api/speed-override", method="POST", body={"speed_kmh": 100.0})
    server.api("/api/logging/start", method="POST")
    asyncio.run(_run_sim_session(clients, server.udp_data_port, duration_s=20.0))
    server.api("/api/logging/stop", method="POST")
    time.sleep(2.0)

    history = server.api("/api/history")
    runs = history["runs"]
    completed = [r for r in runs if r["status"] == "complete"]
    assert len(completed) >= 1
    run = completed[0]
    assert run["sample_count"] > 0

    insights = server.api(f"/api/history/{run['run_id']}/insights")
    assert insights.get("rows", 0) > 0

    # Verify PDF report (both EN and NL) contains expected content
    for lang in ("en", "nl"):
        pdf_bytes, ct = server.api_bytes(f"/api/history/{run['run_id']}/report.pdf?lang={lang}")
        assert ct == "application/pdf"
        assert pdf_bytes[:5] == b"%PDF-", f"lang={lang}: not a valid PDF"
        assert len(pdf_bytes) > 500
        text = _pdf_text(pdf_bytes)
        assert "vibesensor" in text, f"lang={lang}: missing branding"
        # The run has sensor data — PDF should reference it
        assert "front" in text, f"lang={lang}: missing sensor location reference"
        if lang == "nl":
            # Dutch PDF should contain Dutch text
            assert "trillings" in text or "analyse" in text or "meting" in text, (
                "lang=nl: missing Dutch text in PDF"
            )


def test_sim_rear_body_vibration(server: _ServerHandle) -> None:
    """Rear-body vibration profile on rear-left sensor; others idle."""
    clients = _build_clients(
        _SENSOR_NAMES,
        server_host="127.0.0.1",
        server_data_port=server.udp_data_port,
        server_control_port=server.udp_ctrl_port,
    )
    for c in clients:
        if c.name == "Rear Left Wheel":
            c.profile_name = "rear_body"
            c.amp_scale = 1.0
        else:
            c.profile_name = "engine_idle"
            c.amp_scale = 0.05
            c.noise_scale = 0.5

    server.api("/api/speed-override", method="POST", body={"speed_kmh": 90.0})
    server.api("/api/logging/start", method="POST")
    asyncio.run(_run_sim_session(clients, server.udp_data_port, duration_s=20.0))
    server.api("/api/logging/stop", method="POST")
    time.sleep(2.0)

    history = server.api("/api/history")
    completed = [r for r in history["runs"] if r["status"] == "complete"]
    assert len(completed) >= 1
    run = completed[0]
    insights = server.api(f"/api/history/{run['run_id']}/insights")
    assert insights.get("rows", 0) > 0
    assert "sensor_intensity_by_location" in insights

    # Verify PDF report contains sensor intensity data
    pdf_bytes, ct = server.api_bytes(f"/api/history/{run['run_id']}/report.pdf")
    assert ct == "application/pdf"
    assert pdf_bytes[:5] == b"%PDF-"
    text = _pdf_text(pdf_bytes)
    assert "vibesensor" in text
    # Sensor intensity by location should appear in the report
    assert "rear left" in text or "rear-left" in text, (
        "PDF should mention the Rear Left sensor location"
    )


def test_sim_rough_road_all_sensors(server: _ServerHandle) -> None:
    """Rough-road profile on all sensors; verifies multi-sensor detection."""
    clients = _build_clients(
        _SENSOR_NAMES,
        server_host="127.0.0.1",
        server_data_port=server.udp_data_port,
        server_control_port=server.udp_ctrl_port,
        profile_name="rough_road",
    )

    server.api("/api/speed-override", method="POST", body={"speed_kmh": 80.0})
    server.api("/api/logging/start", method="POST")
    asyncio.run(_run_sim_session(clients, server.udp_data_port, duration_s=20.0))
    server.api("/api/logging/stop", method="POST")
    time.sleep(2.0)

    history = server.api("/api/history")
    completed = [r for r in history["runs"] if r["status"] == "complete"]
    assert len(completed) >= 1
    run = completed[0]
    insights = server.api(f"/api/history/{run['run_id']}/insights")
    assert insights.get("rows", 0) > 0
    assert insights.get("sensor_count_used", 0) >= 2

    # Verify PDF report includes multi-sensor data
    pdf_bytes, ct = server.api_bytes(f"/api/history/{run['run_id']}/report.pdf")
    assert ct == "application/pdf"
    assert pdf_bytes[:5] == b"%PDF-"
    text = _pdf_text(pdf_bytes)
    assert "vibesensor" in text
    # Multiple sensors were active — the PDF should reference them
    location_names = ("front left", "front right", "rear left", "rear right")
    sensor_refs = sum(
        1 for name in location_names if name in text or name.replace(" ", "-") in text
    )
    assert sensor_refs >= 2, f"PDF should reference multiple sensor locations, found {sensor_refs}"


def test_sim_delete_history_run(server: _ServerHandle) -> None:
    """Records a run, verifies it appears in history, then deletes it."""
    clients = _build_clients(
        _SENSOR_NAMES[:2],
        server_host="127.0.0.1",
        server_data_port=server.udp_data_port,
        server_control_port=server.udp_ctrl_port,
        profile_name="engine_idle",
    )

    server.api("/api/speed-override", method="POST", body={"speed_kmh": 100.0})
    server.api("/api/logging/start", method="POST")
    asyncio.run(_run_sim_session(clients, server.udp_data_port, duration_s=20.0))
    server.api("/api/logging/stop", method="POST")
    time.sleep(2.0)

    history = server.api("/api/history")
    completed = [r for r in history["runs"] if r["status"] == "complete"]
    assert len(completed) >= 1
    run_id = completed[0]["run_id"]

    # Delete the run
    result = server.api(f"/api/history/{run_id}", method="DELETE")
    assert result["status"] == "deleted"

    # Verify it's gone
    history_after = server.api("/api/history")
    remaining_ids = [r["run_id"] for r in history_after["runs"]]
    assert run_id not in remaining_ids


# ---------------------------------------------------------------------------
# Long tests (marked long_sim, excluded from normal CI)
# ---------------------------------------------------------------------------


@pytest.mark.long_sim
def test_sim_long_wheel_imbalance_extended(server: _ServerHandle) -> None:
    """45-second wheel-imbalance run for stronger statistical confidence."""
    clients = _build_clients(
        _SENSOR_NAMES,
        server_host="127.0.0.1",
        server_data_port=server.udp_data_port,
        server_control_port=server.udp_ctrl_port,
    )
    for c in clients:
        if c.name == "Front Left Wheel":
            c.profile_name = "wheel_imbalance"
            c.amp_scale = 1.0
        else:
            c.profile_name = "engine_idle"
            c.amp_scale = 0.05
            c.noise_scale = 0.6

    server.api("/api/speed-override", method="POST", body={"speed_kmh": 100.0})
    server.api("/api/logging/start", method="POST")
    asyncio.run(_run_sim_session(clients, server.udp_data_port, duration_s=45.0))
    server.api("/api/logging/stop", method="POST")
    time.sleep(3.0)

    history = server.api("/api/history")
    completed = [r for r in history["runs"] if r["status"] == "complete"]
    assert len(completed) >= 1
    run = completed[0]
    assert run["sample_count"] > 100

    insights = server.api(f"/api/history/{run['run_id']}/insights")
    wheel_findings = [
        f
        for f in insights.get("findings", [])
        if "wheel" in str(f.get("suspected_source", "")).lower()
    ]
    assert len(wheel_findings) > 0


@pytest.mark.long_sim
def test_sim_long_one_wheel_mild_rear_left(server: _ServerHandle) -> None:
    """40-second mild wheel scenario on rear-left."""
    clients = _build_clients(
        ["front-left", "front-right", "rear-left", "rear-right"],
        server_host="127.0.0.1",
        server_data_port=server.udp_data_port,
        server_control_port=server.udp_ctrl_port,
    )
    apply_one_wheel_mild_scenario(clients, "rear-left")

    server.api("/api/speed-override", method="POST", body={"speed_kmh": 100.0})
    server.api("/api/logging/start", method="POST")
    asyncio.run(_run_sim_session(clients, server.udp_data_port, duration_s=40.0))
    server.api("/api/logging/stop", method="POST")
    time.sleep(3.0)

    history = server.api("/api/history")
    completed = [r for r in history["runs"] if r["status"] == "complete"]
    assert len(completed) >= 1
    insights = server.api(f"/api/history/{completed[0]['run_id']}/insights")
    assert insights.get("rows", 0) > 100


@pytest.mark.long_sim
def test_sim_long_high_speed(server: _ServerHandle) -> None:
    """30-second run at high speed (140 km/h) with wheel imbalance."""
    clients = _build_clients(
        _SENSOR_NAMES,
        server_host="127.0.0.1",
        server_data_port=server.udp_data_port,
        server_control_port=server.udp_ctrl_port,
    )
    for c in clients:
        if c.name == "Rear Right Wheel":
            c.profile_name = "wheel_imbalance"
            c.amp_scale = 0.8
        else:
            c.profile_name = "engine_idle"
            c.amp_scale = 0.05
            c.noise_scale = 0.5

    server.api("/api/speed-override", method="POST", body={"speed_kmh": 140.0})
    server.api("/api/logging/start", method="POST")
    asyncio.run(_run_sim_session(clients, server.udp_data_port, duration_s=30.0))
    server.api("/api/logging/stop", method="POST")
    time.sleep(3.0)

    history = server.api("/api/history")
    completed = [r for r in history["runs"] if r["status"] == "complete"]
    assert len(completed) >= 1
    run = completed[0]
    insights = server.api(f"/api/history/{run['run_id']}/insights")
    assert insights.get("rows", 0) > 50


@pytest.mark.long_sim
def test_sim_long_low_speed(server: _ServerHandle) -> None:
    """30-second run at low speed (40 km/h)."""
    clients = _build_clients(
        _SENSOR_NAMES,
        server_host="127.0.0.1",
        server_data_port=server.udp_data_port,
        server_control_port=server.udp_ctrl_port,
        profile_name="rough_road",
    )

    server.api("/api/speed-override", method="POST", body={"speed_kmh": 40.0})
    server.api("/api/logging/start", method="POST")
    asyncio.run(_run_sim_session(clients, server.udp_data_port, duration_s=30.0))
    server.api("/api/logging/stop", method="POST")
    time.sleep(3.0)

    history = server.api("/api/history")
    completed = [r for r in history["runs"] if r["status"] == "complete"]
    assert len(completed) >= 1


@pytest.mark.long_sim
def test_sim_long_multiple_sequential_runs(server: _ServerHandle) -> None:
    """Three sequential 20-second runs; verifies history accumulates correctly."""
    profiles = ["wheel_imbalance", "rough_road", "engine_idle"]

    for i, profile in enumerate(profiles):
        clients = _build_clients(
            _SENSOR_NAMES[:3],
            server_host="127.0.0.1",
            server_data_port=server.udp_data_port,
            server_control_port=server.udp_ctrl_port,
            profile_name=profile,
        )
        server.api("/api/speed-override", method="POST", body={"speed_kmh": 80.0 + i * 10})
        server.api("/api/logging/start", method="POST")
        asyncio.run(_run_sim_session(clients, server.udp_data_port, duration_s=20.0))
        server.api("/api/logging/stop", method="POST")
        time.sleep(2.0)

    history = server.api("/api/history")
    completed = [r for r in history["runs"] if r["status"] == "complete"]
    assert len(completed) >= 3, f"Expected ≥3 completed runs, got {len(completed)}"
