"""Long-running simulated-run tests for the VibeSensor history feature.

These tests carry the ``long_sim`` marker and are excluded from normal CI.
Run them explicitly with ``pytest -m long_sim``.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from test_history_simulated_runs import (
    _SENSOR_NAMES,
    _build_clients,
    _run_sim_session,
    _ServerHandle,
    apply_one_wheel_mild_scenario,
)

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
