"""Shared fixtures for history / simulated-run tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from test_history_simulated_runs import (
    ROOT,
    _free_port,
    _ServerHandle,
    _wait_health,
    _write_temp_config,
)


@pytest.fixture()
def server(tmp_path: Path) -> Any:  # noqa: ANN401
    """Start a real VibeSensor server in a subprocess and yield a handle."""
    http_port = _free_port()
    udp_data = _free_port()
    udp_ctrl = _free_port()
    cfg = _write_temp_config(tmp_path, http_port, udp_data, udp_ctrl)

    env = {**os.environ, "VIBESENSOR_SERVE_STATIC": "0"}

    proc = subprocess.Popen(
        [sys.executable, "-m", "vibesensor.app", "--config", str(cfg)],
        cwd=str(ROOT / "server"),
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
