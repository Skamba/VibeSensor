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
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest
import yaml

from tests_e2e.e2e_helpers import CAPPED_RECORDING_S, ROOT, api_json
from vibesensor.domain.analysis_settings import ANALYSIS_SETTINGS_REFERENCE_KEYS
from vibesensor.simulator.profiles import SIMULATOR_CAR_ASPECTS
from vibesensor.updates.boot_check import not_working_reason
from vibesensor.updates.isolated_server_runtime import (
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
# Starts of one server whose UDP ports another process bound first (see
# ``_running_server``); a third collision in a row is not a race.
_START_ATTEMPTS = 3
_PR_SET_PDEATHSIG = 1


@dataclass(frozen=True)
class E2EServer:
    runtime: IsolatedRuntimePaths
    base_url: str
    sim_data_port: int
    sim_control_port: int
    sim_gps_port: int
    log_path: Path


class _UdpPortTakenError(RuntimeError):
    """The server exited at startup because another process held one of its UDP ports."""


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((_HOST, 0))
        return int(sock.getsockname()[1])


@contextmanager
def _reserved_tcp_port() -> Iterator[int]:
    """Hold a free TCP port for this worker's listener, for the whole session.

    Granian (the server) and the simulator's GPS receiver bind their listeners
    with ``SO_REUSEPORT``. A listener started on a port another worker's
    listener already holds does not fail: both serve it and the kernel splits
    the connections between them, so requests land on the other worker's
    server. A port that was only probed free can be handed to another worker
    before its listener binds it, and the GPS port is free between simulator
    runs. A bound (never listening) ``SO_REUSEPORT`` socket keeps every other
    bind, port-0 probes included, off the port while this worker's listeners
    can still join it. It receives no connections because it never listens.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind((_HOST, 0))
        yield int(sock.getsockname()[1])


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
            tail = _tail(log_path)
            port_taken = "[Errno 98] Address already in use" in tail
            raise (_UdpPortTakenError if port_taken else RuntimeError)(
                f"e2e server exited with {process.returncode} before becoming ready:\n{tail}"
            )
        try:
            with urlopen(request, timeout=2.0) as resp:
                last = json.loads(resp.read().decode("utf-8", errors="replace"))
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last = exc
        else:
            if isinstance(last, dict) and last.get("background_task_failures"):
                raise RuntimeError(f"e2e server startup task failed: {last}")
            # The post-update boot check's rule: the server works, whatever
            # operational warnings (sensors, GPS, root side) its status carries.
            if not_working_reason(last) is None:
                return
        time.sleep(0.25)
    raise RuntimeError(f"e2e server not ready after {_STARTUP_TIMEOUT_S}s; last={last!r}")


def _activate_simulator_car(base_url: str) -> None:
    """Give the fresh server an active car with the simulator's specs.

    A server has no car (and so no order references) until one is added; the
    simulated faults are placed with these specs.
    """
    aspects = {key: SIMULATOR_CAR_ASPECTS[key] for key in ANALYSIS_SETTINGS_REFERENCE_KEYS}
    created = api_json(
        base_url,
        "/api/settings/cars",
        method="POST",
        body={"name": "Simulator car", "type": "sedan", "aspects": aspects},
    )
    car_id = created["cars"][-1]["id"]
    api_json(base_url, "/api/settings/cars/active", method="PUT", body={"car_id": car_id})


def _tail(path: Path, lines: int = 80) -> str:
    if not path.exists():
        return "<missing>"
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


class PowerCut:
    """Stops a running e2e server the way a power cut does and starts it again."""

    def __init__(self, server: E2EServer, process: subprocess.Popen[str]) -> None:
        self.server = server
        self.process = process

    @property
    def env(self) -> dict[str, str]:
        return _env_for(self.server)

    def cut_and_restore(self) -> None:
        """SIGKILL the server (no Stop, no shutdown) and start it on the same data."""
        os.killpg(self.process.pid, signal.SIGKILL)
        self.process.wait(timeout=10.0)
        env = build_isolated_server_env(
            self.server.runtime.root, repo_root=ROOT, extra_env={"VIBESENSOR_SERVE_STATIC": "0"}
        )
        self.process = _spawn(self.server, env)
        _wait_ready(self.server.base_url, self.process, self.server.log_path)


@contextmanager
def _running_server(
    runtime_root: Path, *, config_overrides: dict[str, object] | None = None
) -> Iterator[PowerCut]:
    with _reserved_tcp_port() as http_port, _reserved_tcp_port() as gps_port:
        for attempt in range(1, _START_ATTEMPTS + 1):
            # The server binds its UDP ports itself, without SO_REUSEPORT, so they
            # cannot be held for it: another process can bind one between this
            # probe and the server's start. The server then exits; retry on fresh
            # ports.
            server, process = _start_server(
                runtime_root / f"start-{attempt}",
                http_port=http_port,
                udp_data_port=_free_udp_port(),
                udp_control_port=_free_udp_port(),
                gps_port=gps_port,
                config_overrides=config_overrides,
            )
            try:
                _wait_ready(server.base_url, process, server.log_path)
            except _UdpPortTakenError:
                terminate_subprocess(process)
                if attempt == _START_ATTEMPTS:
                    raise
                continue
            except BaseException:
                terminate_subprocess(process)
                raise
            break
        power = PowerCut(server, process)
        try:
            _activate_simulator_car(server.base_url)
            yield power
        finally:
            terminate_subprocess(power.process)


def _start_server(
    runtime_root: Path,
    *,
    http_port: int,
    udp_data_port: int,
    udp_control_port: int,
    gps_port: int,
    config_overrides: dict[str, object] | None,
) -> tuple[E2EServer, subprocess.Popen[str]]:
    runtime = build_isolated_server_config(
        _BASE_CONFIG,
        runtime_root,
        host=_HOST,
        port=http_port,
        udp_data_port=udp_data_port,
        udp_control_port=udp_control_port,
        data_seed_dir=_DATA_SEED_DIR,
    )
    config = yaml.safe_load(runtime.config_path.read_text(encoding="utf-8"))
    # The simulator reports its speed as a GPS receiver on this port.
    config["gps"] = {"gps_enabled": True, "gpsd_port": gps_port}
    config.update(config_overrides or {})
    runtime.config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    env = build_isolated_server_env(
        runtime.root, repo_root=ROOT, extra_env={"VIBESENSOR_SERVE_STATIC": "0"}
    )
    server = E2EServer(
        runtime=runtime,
        base_url=f"http://{_HOST}:{http_port}",
        sim_data_port=udp_data_port,
        sim_control_port=udp_control_port,
        sim_gps_port=gps_port,
        log_path=runtime.root / "server.log",
    )
    server.log_path.write_text("", encoding="utf-8")
    return server, _spawn(server, env)


def _spawn(server: E2EServer, env: dict[str, str]) -> subprocess.Popen[str]:
    with server.log_path.open("a", encoding="utf-8") as log_file:
        return subprocess.Popen(
            build_server_subprocess_cmd(server.runtime.config_path),
            cwd=str(ROOT),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=_start_session_dying_with_parent,
        )


def _env_for(server: E2EServer) -> dict[str, str]:
    return {
        "base_url": server.base_url,
        "sim_host": _HOST,
        "sim_data_port": str(server.sim_data_port),
        "sim_control_port": str(server.sim_control_port),
        "sim_gps_port": str(server.sim_gps_port),
    }


@pytest.fixture(scope="session")
def e2e_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[E2EServer]:
    with _running_server(tmp_path_factory.mktemp("e2e-server")) as power:
        yield power.server


@pytest.fixture
def e2e_env(e2e_server: E2EServer) -> dict[str, str]:
    return _env_for(e2e_server)


@pytest.fixture
def capped_e2e_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[E2EServer]:
    """A dedicated server whose recordings auto-stop after ``CAPPED_RECORDING_S``."""
    with _running_server(
        tmp_path_factory.mktemp("e2e-capped-server"),
        config_overrides={"recording": {"max_duration_s": CAPPED_RECORDING_S}},
    ) as power:
        yield power.server


@pytest.fixture
def capped_e2e_env(capped_e2e_server: E2EServer) -> dict[str, str]:
    return _env_for(capped_e2e_server)


@pytest.fixture
def power_cut(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PowerCut]:
    """A dedicated server a test may stop as a power cut does and start again."""
    with _running_server(tmp_path_factory.mktemp("e2e-power-cut-server")) as power:
        yield power


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    funcargs = getattr(item, "funcargs", {})
    for name in ("e2e_server", "capped_e2e_server"):
        server = funcargs.get(name)
        if report.failed and isinstance(server, E2EServer):
            report.sections.append((f"{name} log tail", _tail(server.log_path)))
            report.sections.append(
                (f"{name} app log tail", _tail(server.runtime.data_dir / "app.log"))
            )
    return report
