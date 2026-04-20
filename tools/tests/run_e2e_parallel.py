#!/usr/bin/env python3
"""Run process-backed e2e shards with cached duration balancing and cleanup hooks."""

from __future__ import annotations

import argparse
import atexit
import importlib.util
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from vibesensor.shared.subprocess_server import (
    IsolatedRuntimePaths,
    build_isolated_server_config,
    build_isolated_server_env,
    build_server_subprocess_cmd,
    start_server_subprocess,
    terminate_subprocess,
)


def _load_parallel_runner_support():
    helper_path = Path(__file__).with_name("_parallel_runner_support.py")
    spec = importlib.util.spec_from_file_location(
        "_parallel_runner_support", helper_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load parallel runner helpers from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_parallel_runner_support = _load_parallel_runner_support()
resolve_duration_cache_path = _parallel_runner_support.duration_cache_path
read_duration_cache = _parallel_runner_support.load_duration_cache
merge_duration_observations = _parallel_runner_support.merge_duration_observations
read_observed_durations_from_junit = (
    _parallel_runner_support.observed_durations_from_junit
)
collect_normalized_test_ids = _parallel_runner_support.parse_collected_test_ids


def _normalize_collected_test_id(line: str) -> str | None:
    if line.startswith("tests/") or line.startswith("tests_e2e/"):
        return f"apps/server/{line}"
    if line.startswith("apps/server/tests/") or line.startswith(
        "apps/server/tests_e2e/"
    ):
        return line
    return None


def _parse_collected_test_ids(output: str) -> list[str]:
    return collect_normalized_test_ids(output, normalize=_normalize_collected_test_id)


def _duration_cache_path(env: Mapping[str, str] | None = None) -> Path:
    return resolve_duration_cache_path(
        _DURATION_CACHE_ENV,
        "e2e-duration-cache.json",
        env=env,
    )


def _load_duration_cache(path: Path) -> dict[str, float]:
    return read_duration_cache(path, emit=_emit, label="e2e-parallel")


def _merge_duration_observations(
    cached: Mapping[str, float],
    observed: Mapping[str, float],
) -> dict[str, float]:
    return merge_duration_observations(cached, observed)


def _observed_durations_from_junit(
    junit_path: Path,
    selected_tests: list[str],
) -> dict[str, float]:
    return read_observed_durations_from_junit(
        junit_path,
        selected_tests,
        emit=_emit,
        label="e2e-parallel",
    )


def collect_test_ids(pytest_args: list[str]) -> list[str]:
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", *pytest_args]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stdout.write(result.stdout or "")
        sys.stderr.write(result.stderr or "")
        raise SystemExit(result.returncode)
    return _parse_collected_test_ids(result.stdout or "")


ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "artifacts" / "ai" / "logs" / "e2e_parallel"
PRINT_LOCK = threading.Lock()
_DURATION_CACHE_ENV = "VIBESENSOR_E2E_DURATION_CACHE"
_DEFAULT_MIN_SHARDS = 6
_DEFAULT_DURATION = 3.0
_DEFAULT_BASE_CONFIG = ROOT / "apps" / "server" / "config.docker.yaml"
_DEFAULT_DATA_SEED_DIR = ROOT / "apps" / "server" / "vibesensor" / "data"
_ACTIVE_PROCESSES: dict[str, subprocess.Popen[str]] = {}
_ACTIVE_PROCESSES_LOCK = threading.Lock()
_ACTIVE_RUNTIME_ROOTS: set[Path] = set()
_ACTIVE_RUNTIME_ROOTS_LOCK = threading.Lock()
_CLEANUP_HOOKS_REGISTERED = False
_PREVIOUS_SIGNAL_HANDLERS: dict[int, object] = {}


@dataclass(frozen=True)
class ShardConfig:
    index: int
    count: int
    tests: list[str]
    runtime: IsolatedRuntimePaths
    http_port: int
    sim_data_port: int
    sim_control_port: int
    sim_client_control_base: int
    log_path: Path
    junit_path: Path

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.http_port}"

    @property
    def app_log_path(self) -> Path:
        return self.runtime.data_dir / "app.log"

    @property
    def sim_log_path(self) -> Path:
        return self.runtime.data_dir / "sim_sender.log"


@dataclass(frozen=True)
class ShardResult:
    index: int
    return_code: int
    duration_s: float
    log_path: Path
    selected_tests: int


# Tests exceeding SLOW_TEST_THRESHOLD get their own dedicated shard.
# Observed timings are loaded from and saved back to a local cache so the
# runner can rebalance without hand-maintained per-test constants.
SLOW_TEST_THRESHOLD = 2.5


def _write_duration_cache(path: Path, durations: Mapping[str, float]) -> None:
    payload = {
        test_id: round(duration, 3)
        for test_id, duration in sorted(durations.items())
        if duration > 0
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"{json.dumps(payload, indent=2, sort_keys=True)}\n", encoding="utf-8"
        )
    except OSError:
        _emit(f"[e2e-parallel] failed to update duration cache: {path}")


def _estimate_duration(test_id: str, durations: Mapping[str, float]) -> float:
    return durations.get(test_id, _DEFAULT_DURATION)


def _assign_shards_by_duration(
    collected: list[str], min_shards: int, durations: Mapping[str, float]
) -> list[list[str]]:
    """Assign tests to shards using duration-aware greedy bin-packing.

    Tests with estimated duration > SLOW_TEST_THRESHOLD get dedicated shards.
    Remaining tests are packed greedily into separate remainder shards.
    The total shard count is at least *min_shards*.
    """
    slow_tests: list[tuple[str, float]] = []
    fast_tests: list[tuple[str, float]] = []
    for test_id in collected:
        est = _estimate_duration(test_id, durations)
        if est > SLOW_TEST_THRESHOLD:
            slow_tests.append((test_id, est))
        else:
            fast_tests.append((test_id, est))

    slow_tests.sort(key=lambda t: t[1], reverse=True)
    dedicated: list[list[str]] = [[t[0]] for t in slow_tests]

    remainder_count = max(1, min_shards - len(dedicated))
    remainder: list[list[str]] = [[] for _ in range(remainder_count)]
    remainder_load: list[float] = [0.0] * remainder_count

    fast_tests.sort(key=lambda t: t[1], reverse=True)
    for test_id, est in fast_tests:
        target = min(range(remainder_count), key=lambda idx: remainder_load[idx])
        remainder[target].append(test_id)
        remainder_load[target] += est

    shard_tests = dedicated + remainder
    while shard_tests and not shard_tests[-1]:
        shard_tests.pop()
    return shard_tests


def _emit(line: str) -> None:
    with PRINT_LOCK:
        print(line, flush=True)


def _tail(path: Path, lines: int = 60) -> str:
    if not path.exists():
        return "<missing log>"
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


def _track_active_process(label: str, process: subprocess.Popen[str]) -> None:
    with _ACTIVE_PROCESSES_LOCK:
        _ACTIVE_PROCESSES[label] = process


def _untrack_active_process(label: str) -> None:
    with _ACTIVE_PROCESSES_LOCK:
        _ACTIVE_PROCESSES.pop(label, None)


def _track_active_runtime_root(runtime_root: Path) -> None:
    with _ACTIVE_RUNTIME_ROOTS_LOCK:
        _ACTIVE_RUNTIME_ROOTS.add(runtime_root)


def _untrack_active_runtime_root(runtime_root: Path) -> None:
    with _ACTIVE_RUNTIME_ROOTS_LOCK:
        _ACTIVE_RUNTIME_ROOTS.discard(runtime_root)


def _cleanup_active_processes() -> None:
    with _ACTIVE_PROCESSES_LOCK:
        active_processes = list(_ACTIVE_PROCESSES.items())
    for label, process in active_processes:
        terminate_subprocess(process)
        _untrack_active_process(label)


def _cleanup_active_runtime_roots() -> None:
    with _ACTIVE_RUNTIME_ROOTS_LOCK:
        runtime_roots = list(_ACTIVE_RUNTIME_ROOTS)
    for runtime_root in runtime_roots:
        shutil.rmtree(runtime_root, ignore_errors=True)
        _untrack_active_runtime_root(runtime_root)


def _cleanup_active_resources() -> None:
    _cleanup_active_processes()
    _cleanup_active_runtime_roots()


def _cleanup_on_signal(signum: int, frame) -> None:
    _emit(
        f"[e2e-parallel] received signal {signum}; cleaning up active shard processes"
    )
    _cleanup_active_resources()
    previous = _PREVIOUS_SIGNAL_HANDLERS.get(signum, signal.SIG_DFL)
    if previous is signal.default_int_handler:
        raise KeyboardInterrupt
    if callable(previous):
        previous(signum, frame)
        raise SystemExit(128 + signum)
    raise SystemExit(128 + signum)


def _register_cleanup_hooks() -> None:
    global _CLEANUP_HOOKS_REGISTERED
    if _CLEANUP_HOOKS_REGISTERED:
        return
    atexit.register(_cleanup_active_resources)
    for signum in (signal.SIGINT, signal.SIGTERM):
        _PREVIOUS_SIGNAL_HANDLERS[signum] = signal.getsignal(signum)
        signal.signal(signum, _cleanup_on_signal)
    _CLEANUP_HOOKS_REGISTERED = True


def _api_snapshot(base_url: str, path: str) -> str:
    request = Request(f"{base_url}{path}", headers={"Connection": "close"})
    try:
        with urlopen(request, timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        payload = json.loads(body)
        return json.dumps(payload, indent=2, sort_keys=True)
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return f"<unavailable: {exc}>"


def _wait_health(
    config: ShardConfig,
    server_process: subprocess.Popen[str],
    timeout_s: float = 60.0,
) -> None:
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    health_url = f"{config.base_url}/api/health"
    request = Request(health_url, headers={"Connection": "close"})
    while time.monotonic() < deadline:
        if server_process.poll() is not None:
            raise RuntimeError(
                "Shard server exited before becoming healthy "
                f"(exit {server_process.returncode})."
            )
        try:
            with urlopen(request, timeout=2.0) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Health endpoint returned HTTP {resp.status}")
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            if payload.get("status") not in {"ok", "degraded"}:
                raise RuntimeError(f"Unexpected health payload: {payload}")
            if payload.get("startup_state") != "ready":
                raise RuntimeError(f"Server not ready yet: {payload}")
            if payload.get("background_task_failures"):
                raise RuntimeError(f"Managed startup task failed: {payload}")
            return
        except (
            URLError,
            TimeoutError,
            OSError,
            json.JSONDecodeError,
            RuntimeError,
        ) as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(
        f"Shard server did not become ready before timeout. Last error: {last_error}"
    )


def _print_diagnostics(config: ShardConfig) -> None:
    _emit(
        f"\n=== diagnostics: shard {config.index}/{config.count} runtime ===\n"
        f"runtime_root={config.runtime.root}\n"
        f"config={config.runtime.config_path}"
    )
    if config.runtime.config_path.exists():
        _emit(
            "\n=== diagnostics: generated config ===\n"
            f"{config.runtime.config_path.read_text(encoding='utf-8', errors='replace')}"
        )
    _emit(f"\n=== diagnostics: shard log tail ===\n{_tail(config.log_path, 120)}")
    _emit(f"\n=== diagnostics: app log tail ===\n{_tail(config.app_log_path, 120)}")
    _emit(
        f"\n=== diagnostics: /api/health ===\n"
        f"{_api_snapshot(config.base_url, '/api/health')}"
    )
    _emit(
        f"\n=== diagnostics: /api/clients ===\n"
        f"{_api_snapshot(config.base_url, '/api/clients')}"
    )
    _emit(
        f"\n=== diagnostics: /api/history ===\n"
        f"{_api_snapshot(config.base_url, '/api/history')}"
    )
    if config.sim_log_path.exists():
        _emit(
            f"\n=== diagnostics: simulator log tail ===\n"
            f"{_tail(config.sim_log_path, 120)}"
        )


def _write_log_header(log_file, *, config: ShardConfig) -> None:
    log_file.write(f"runtime_root={config.runtime.root}\n")
    log_file.write(f"config_path={config.runtime.config_path}\n")
    log_file.write(f"base_url={config.base_url}\n")
    log_file.flush()


def _start_logged_process(
    cmd: list[str],
    *,
    env: Mapping[str, str] | None,
    cwd: Path,
    log_file,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        cmd,
        cwd=str(cwd),
        text=True,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=None if env is None else dict(env),
        start_new_session=True,
    )


def _terminate_tracked_process(
    label: str,
    process: subprocess.Popen[str] | None,
) -> None:
    if process is None:
        return
    try:
        terminate_subprocess(process)
    finally:
        _untrack_active_process(label)


def _run_shard_e2e(
    *,
    config: ShardConfig,
    marker: str,
) -> int:
    server_label = f"shard-{config.index}-server"
    pytest_label = f"shard-{config.index}-pytest"
    server_process: subprocess.Popen[str] | None = None
    pytest_process: subprocess.Popen[str] | None = None

    server_env = build_isolated_server_env(
        config.runtime.root,
        repo_root=ROOT,
        extra_env={"VIBESENSOR_SERVE_STATIC": "0"},
    )
    pytest_env = os.environ.copy()
    pytest_env.update(
        {
            "VIBESENSOR_BASE_URL": config.base_url,
            "VIBESENSOR_SIM_SERVER_HOST": "127.0.0.1",
            "VIBESENSOR_SIM_DATA_PORT": str(config.sim_data_port),
            "VIBESENSOR_SIM_CONTROL_PORT": str(config.sim_control_port),
            "VIBESENSOR_SIM_CLIENT_CONTROL_BASE": str(config.sim_client_control_base),
            "VIBESENSOR_SIM_DURATION": "8",
            "VIBESENSOR_SIM_DURATION_LONG": "20",
            "VIBESENSOR_SIM_LOG": str(config.sim_log_path),
        }
    )
    try:
        with config.log_path.open("w", encoding="utf-8") as log_file:
            _write_log_header(log_file, config=config)

            server_cmd = build_server_subprocess_cmd(config.runtime.config_path)
            log_file.write(f"$ {shlex.join(server_cmd)}\n")
            log_file.flush()
            server_process = start_server_subprocess(
                config.runtime.config_path,
                env=server_env,
                cwd=ROOT,
                stdout=log_file,
            )
            _track_active_process(server_label, server_process)
            _wait_health(config, server_process)

            pytest_cmd = [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-n",
                "0",
                "--junitxml",
                str(config.junit_path),
                "-m",
                marker,
                *config.tests,
            ]
            log_file.write(f"$ {shlex.join(pytest_cmd)}\n")
            log_file.flush()
            pytest_process = _start_logged_process(
                pytest_cmd,
                env=pytest_env,
                cwd=ROOT,
                log_file=log_file,
            )
            _track_active_process(pytest_label, pytest_process)
            rc = pytest_process.wait()
        if rc != 0:
            _print_diagnostics(config)
        return rc if rc is not None else 1
    except Exception:
        _print_diagnostics(config)
        raise
    finally:
        _terminate_tracked_process(pytest_label, pytest_process)
        _terminate_tracked_process(server_label, server_process)


def _resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else (ROOT / path)


def _validate_port(port: int, *, label: str) -> int:
    if not 1 <= port <= 65535:
        raise ValueError(f"{label} must be 1-65535, got {port}")
    return port


def _build_shard_config(
    *,
    source_config: Path,
    shard_index: int,
    shard_count: int,
    tests: list[str],
    http_port_base: int,
    sim_data_port_base: int,
    sim_control_port_base: int,
) -> ShardConfig:
    http_port = _validate_port(
        http_port_base + (shard_index - 1),
        label=f"shard {shard_index} http port",
    )
    sim_data_port = _validate_port(
        sim_data_port_base + (shard_index - 1),
        label=f"shard {shard_index} sim data port",
    )
    sim_control_port = _validate_port(
        sim_control_port_base + (shard_index - 1),
        label=f"shard {shard_index} sim control port",
    )

    runtime_root = Path(tempfile.mkdtemp(prefix=f"vibesensor-e2e-shard-{shard_index}-"))
    _track_active_runtime_root(runtime_root)
    runtime = build_isolated_server_config(
        source_config,
        runtime_root,
        host="127.0.0.1",
        port=http_port,
        udp_data_port=sim_data_port,
        udp_control_port=sim_control_port,
        config_name=f"shard-{shard_index}.yaml",
        data_seed_dir=_DEFAULT_DATA_SEED_DIR,
    )
    return ShardConfig(
        index=shard_index,
        count=shard_count,
        tests=tests,
        runtime=runtime,
        http_port=http_port,
        sim_data_port=sim_data_port,
        sim_control_port=sim_control_port,
        sim_client_control_base=9100 + ((shard_index - 1) * 100),
        log_path=LOG_DIR / f"shard-{shard_index}.log",
        junit_path=LOG_DIR / f"shard-{shard_index}.xml",
    )


def _shard_worker(
    *,
    config: ShardConfig,
    marker: str,
    results: dict[int, ShardResult],
    lock: threading.Lock,
) -> None:
    started = time.monotonic()
    rc = 1
    try:
        if not config.tests:
            _emit(
                f"[e2e-parallel] shard {config.index}/{config.count}: "
                "no tests selected; skipping"
            )
            rc = 0
        else:
            _emit(
                f"[e2e-parallel] shard {config.index}/{config.count}: "
                f"tests={len(config.tests)} log={config.log_path}"
            )
            rc = _run_shard_e2e(
                config=config,
                marker=marker,
            )
            if rc != 0:
                _emit(
                    f"[e2e-parallel] shard {config.index}/{config.count} failed "
                    f"(exit {rc}) tail:\n{_tail(config.log_path)}"
                )
    except Exception as exc:
        rc = 1
        _emit(f"[e2e-parallel] shard {config.index}/{config.count} crashed: {exc!r}")
    finally:
        shutil.rmtree(config.runtime.root, ignore_errors=True)
        _untrack_active_runtime_root(config.runtime.root)
        elapsed = time.monotonic() - started
        with lock:
            results[config.index] = ShardResult(
                index=config.index,
                return_code=rc,
                duration_s=elapsed,
                log_path=config.log_path,
                selected_tests=len(config.tests),
            )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run process-backed e2e tests in isolated parallel shards."
    )
    parser.add_argument(
        "--shards",
        type=int,
        default=_DEFAULT_MIN_SHARDS,
        help="Minimum number of parallel shards (actual count may be higher for duration balance).",
    )
    parser.add_argument(
        "--fast-e2e",
        action="store_true",
        help="Use fast marker expression (`e2e and not long_sim`).",
    )
    parser.add_argument(
        "--pytest-marker",
        default=None,
        help="Override pytest marker expression for e2e selection.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_DEFAULT_BASE_CONFIG,
        help="Base YAML config cloned into each shard runtime root.",
    )
    parser.add_argument(
        "--http-port-base",
        type=int,
        default=18020,
        help="Base host HTTP port; shard N uses base + (N-1).",
    )
    parser.add_argument(
        "--sim-data-port-base",
        type=int,
        default=19020,
        help="Base host simulator UDP data port; shard N uses base + (N-1).",
    )
    parser.add_argument(
        "--sim-control-port-base",
        type=int,
        default=19120,
        help="Base host simulator UDP control port; shard N uses base + (N-1).",
    )
    args = parser.parse_args()
    if args.shards < 1:
        raise SystemExit("--shards must be >= 1")
    return args


def main() -> int:
    args = _parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _register_cleanup_hooks()

    source_config = _resolve_repo_path(args.config).resolve()
    if not source_config.is_file():
        raise SystemExit(f"Base config does not exist: {source_config}")

    marker = args.pytest_marker
    if marker is None:
        marker = "e2e and not long_sim" if args.fast_e2e else "e2e"

    collected = collect_test_ids(["-m", marker, "apps/server/tests_e2e"])
    duration_cache_path = _duration_cache_path(os.environ)
    duration_cache = _load_duration_cache(duration_cache_path)
    if duration_cache:
        _emit(
            f"[e2e-parallel] loaded {len(duration_cache)} cached test durations from "
            f"{duration_cache_path}"
        )

    shard_test_ids = _assign_shards_by_duration(collected, args.shards, duration_cache)
    num_shards = len(shard_test_ids)

    _emit(
        f"[e2e-parallel] collected {len(collected)} tests for marker '{marker}' "
        f"across {num_shards} shards (min requested: {args.shards})"
    )

    shards: list[ShardConfig] = []
    for shard_index in range(1, num_shards + 1):
        shards.append(
            _build_shard_config(
                source_config=source_config,
                shard_index=shard_index,
                shard_count=num_shards,
                tests=shard_test_ids[shard_index - 1],
                http_port_base=args.http_port_base,
                sim_data_port_base=args.sim_data_port_base,
                sim_control_port_base=args.sim_control_port_base,
            )
        )

    started = time.monotonic()
    results: dict[int, ShardResult] = {}
    results_lock = threading.Lock()
    threads: list[threading.Thread] = []
    for shard in shards:
        thread = threading.Thread(
            target=_shard_worker,
            kwargs={
                "config": shard,
                "marker": marker,
                "results": results,
                "lock": results_lock,
            },
            daemon=False,
        )
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()

    observed_durations: dict[str, float] = {}
    for shard in shards:
        observed_durations.update(
            _observed_durations_from_junit(shard.junit_path, shard.tests)
        )
    if observed_durations:
        merged_durations = _merge_duration_observations(
            duration_cache, observed_durations
        )
        _write_duration_cache(duration_cache_path, merged_durations)
        _emit(
            f"[e2e-parallel] updated duration cache with {len(observed_durations)} observed "
            f"test timings at {duration_cache_path}"
        )

    elapsed = time.monotonic() - started
    _emit("\n=== e2e parallel summary ===")
    overall_ok = True
    for shard_index in range(1, num_shards + 1):
        result = results.get(shard_index)
        if result is None:
            overall_ok = False
            _emit(f"- shard {shard_index}/{num_shards}: FAIL missing result")
            continue
        if result.return_code == 0:
            _emit(
                f"- shard {result.index}/{num_shards}: PASS tests={result.selected_tests} "
                f"time={result.duration_s:.1f}s log={result.log_path}"
            )
            continue
        overall_ok = False
        _emit(
            f"- shard {result.index}/{num_shards}: FAIL tests={result.selected_tests} "
            f"exit={result.return_code} time={result.duration_s:.1f}s log={result.log_path}"
        )
    _emit(f"total wall time: {elapsed:.1f}s")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
