"""Process-backed e2e fixtures: one isolated server per pytest(-xdist) worker.

Each worker clones ``config.docker.yaml`` into its own runtime directory, binds
the server and simulator to free loopback ports, and tears the server down at
session end. Run with ``make test-e2e`` (see ``docs/testing.md``).
"""

from __future__ import annotations

import ctypes
import json
import os
import signal
import socket
import subprocess
import time
from collections.abc import Generator, Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest

from tests_e2e.e2e_helpers import ROOT
from vibesensor.use_cases.isolated_server_runtime import (
    IsolatedRuntimePaths,
    build_isolated_server_config,
    build_isolated_server_env,
    build_server_subprocess_cmd,
    terminate_subprocess,
)

_BASE_CONFIG = ROOT / "apps" / "server" / "config.docker.yaml"
_DATA_SEED_DIR = ROOT / "apps" / "server" / "vibesensor" / "data"
_HOST = "127.0.0.1"
_STARTUP_TIMEOUT_S = 60.0
# The simulator binds one UDP control port per simulated sensor starting at
# its client-control base; reserve room for the largest fleet the tests use.
_SIM_CLIENT_PORT_SLOTS = 8
_PR_SET_PDEATHSIG = 1


@dataclass(frozen=True)
class E2EServer:
    runtime: IsolatedRuntimePaths
    base_url: str
    sim_data_port: int
    sim_control_port: int
    sim_client_control_base: int
    log_path: Path


def _free_port(kind: int) -> int:
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind((_HOST, 0))
        return int(sock.getsockname()[1])


def _free_udp_port_block(size: int) -> int:
    """Return a base port whose next *size* UDP ports are currently free."""
    for _ in range(50):
        base = _free_port(socket.SOCK_DGRAM)
        if base + size > 65535:
            continue
        socks: list[socket.socket] = []
        try:
            for offset in range(size):
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                socks.append(sock)
                sock.bind(("0.0.0.0", base + offset))
        except OSError:
            continue
        finally:
            for sock in socks:
                sock.close()
        return base
    raise RuntimeError(f"no block of {size} free UDP ports found")


def _start_session_dying_with_parent() -> None:
    """Child pre-exec: own process group, SIGTERM when the pytest worker dies."""
    os.setsid()
    ctypes.CDLL(None, use_errno=True).prctl(_PR_SET_PDEATHSIG, signal.SIGTERM)


def _wait_ready(base_url: str, process: subprocess.Popen[str], log_path: Path) -> None:
    deadline = time.monotonic() + _STARTUP_TIMEOUT_S
    request = Request(f"{base_url}/api/health", headers={"Connection": "close"})
    last: object = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"e2e server exited with {process.returncode} before becoming ready:\n"
                f"{_tail(log_path)}"
            )
        try:
            with urlopen(request, timeout=2.0) as resp:
                last = json.loads(resp.read().decode("utf-8", errors="replace"))
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last = exc
        else:
            if isinstance(last, dict) and last.get("background_task_failures"):
                raise RuntimeError(f"e2e server startup task failed: {last}")
            if (
                isinstance(last, dict)
                and last.get("status") in {"ok", "degraded"}
                and last.get("startup_state") == "ready"
            ):
                return
        time.sleep(0.25)
    raise RuntimeError(f"e2e server not ready after {_STARTUP_TIMEOUT_S}s; last={last!r}")


def _tail(path: Path, lines: int = 80) -> str:
    if not path.exists():
        return "<missing>"
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


@pytest.fixture(scope="session")
def e2e_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[E2EServer]:
    http_port = _free_port(socket.SOCK_STREAM)
    sim_data_port = _free_port(socket.SOCK_DGRAM)
    sim_control_port = _free_port(socket.SOCK_DGRAM)
    runtime = build_isolated_server_config(
        _BASE_CONFIG,
        tmp_path_factory.mktemp("e2e-server"),
        host=_HOST,
        port=http_port,
        udp_data_port=sim_data_port,
        udp_control_port=sim_control_port,
        data_seed_dir=_DATA_SEED_DIR,
    )
    env = build_isolated_server_env(
        runtime.root, repo_root=ROOT, extra_env={"VIBESENSOR_SERVE_STATIC": "0"}
    )
    log_path = runtime.root / "server.log"
    server = E2EServer(
        runtime=runtime,
        base_url=f"http://{_HOST}:{http_port}",
        sim_data_port=sim_data_port,
        sim_control_port=sim_control_port,
        sim_client_control_base=_free_udp_port_block(_SIM_CLIENT_PORT_SLOTS),
        log_path=log_path,
    )
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            build_server_subprocess_cmd(runtime.config_path),
            cwd=str(ROOT),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=_start_session_dying_with_parent,
        )
    try:
        _wait_ready(server.base_url, process, log_path)
        yield server
    finally:
        terminate_subprocess(process)


@pytest.fixture
def e2e_env(e2e_server: E2EServer) -> dict[str, str]:
    return {
        "base_url": e2e_server.base_url,
        "sim_host": _HOST,
        "sim_data_port": str(e2e_server.sim_data_port),
        "sim_control_port": str(e2e_server.sim_control_port),
        "sim_client_control_base": str(e2e_server.sim_client_control_base),
    }


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    server = getattr(item, "funcargs", {}).get("e2e_server")
    if report.failed and isinstance(server, E2EServer):
        report.sections.append(("e2e server log tail", _tail(server.log_path)))
        report.sections.append(("e2e app log tail", _tail(server.runtime.data_dir / "app.log")))
    return report
