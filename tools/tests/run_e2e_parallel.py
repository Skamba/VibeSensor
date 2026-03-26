#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
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
from urllib.request import urlopen

from _parallel_runner_support import (
    duration_cache_path as resolve_duration_cache_path,
    load_duration_cache as read_duration_cache,
    merge_duration_observations,
    observed_durations_from_junit as read_observed_durations_from_junit,
    parse_collected_test_ids as collect_normalized_test_ids,
)


def _normalize_collected_test_id(line: str) -> str | None:
    if line.startswith("tests/") or line.startswith("tests_e2e/"):
        return f"apps/server/{line}"
    if line.startswith("apps/server/tests/") or line.startswith(
        "apps/server/tests_e2e/"
    ):
        return line
    return None


def collect_test_ids(pytest_args: list[str]) -> list[str]:
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", *pytest_args]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stdout.write(result.stdout or "")
        sys.stderr.write(result.stderr or "")
        raise SystemExit(result.returncode)
    return collect_normalized_test_ids(
        result.stdout or "",
        normalize=_normalize_collected_test_id,
    )


ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "artifacts" / "ai" / "logs" / "e2e_parallel"
PRINT_LOCK = threading.Lock()
_SKIP_BUILD_ENV = "VIBESENSOR_E2E_SKIP_BUILD"
_DURATION_CACHE_ENV = "VIBESENSOR_E2E_DURATION_CACHE"
_DEFAULT_MIN_SHARDS = 6
_DEFAULT_DOCKERFILE = "apps/server/Dockerfile.e2e"
_DEFAULT_DURATION = 3.0
_SCOPE_LABEL = "com.vibesensor.role=e2e-shard"
_RUN_LABEL_KEY = "com.vibesensor.run-id"
_ACTIVE_CONTAINERS: set[str] = set()
_ACTIVE_CONTAINERS_LOCK = threading.Lock()
_CLEANUP_HOOKS_REGISTERED = False
_PREVIOUS_SIGNAL_HANDLERS: dict[int, object] = {}


@dataclass(frozen=True)
class ShardConfig:
    index: int
    count: int
    tests: list[str]
    container_name: str
    data_dir: Path
    http_port: int
    sim_data_port: int
    sim_control_port: int
    sim_client_control_base: int
    log_path: Path
    junit_path: Path


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

    # Sort slow tests by duration descending for consistent ordering.
    slow_tests.sort(key=lambda t: t[1], reverse=True)

    # Each slow test gets a dedicated shard.
    dedicated: list[list[str]] = [[t[0]] for t in slow_tests]

    # Pack remaining fast tests into separate remainder shards.
    remainder_count = max(1, min_shards - len(dedicated))
    remainder: list[list[str]] = [[] for _ in range(remainder_count)]
    remainder_load: list[float] = [0.0] * remainder_count

    fast_tests.sort(key=lambda t: t[1], reverse=True)
    for test_id, est in fast_tests:
        target = min(range(remainder_count), key=lambda idx: remainder_load[idx])
        remainder[target].append(test_id)
        remainder_load[target] += est

    shard_tests = dedicated + remainder

    # Remove any empty trailing shards.
    while shard_tests and not shard_tests[-1]:
        shard_tests.pop()

    return shard_tests


def _emit(line: str) -> None:
    with PRINT_LOCK:
        print(line, flush=True)


def _run(cmd: list[str], *, log_path: Path) -> int:
    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write(f"$ {shlex.join(cmd)}\n")
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        output = proc.stdout or ""
        if output:
            log_file.write(output)
            if not output.endswith("\n"):
                log_file.write("\n")
    return proc.returncode if proc.returncode is not None else 1


def _tail(path: Path, lines: int = 60) -> str:
    if not path.exists():
        return "<missing log>"
    content = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(content[-lines:])


def _force_remove_container(container_name: str) -> int:
    result = subprocess.run(
        ["docker", "rm", "-f", container_name],
        cwd=str(ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode


def _track_active_container(container_name: str) -> None:
    with _ACTIVE_CONTAINERS_LOCK:
        _ACTIVE_CONTAINERS.add(container_name)


def _untrack_active_container(container_name: str) -> None:
    with _ACTIVE_CONTAINERS_LOCK:
        _ACTIVE_CONTAINERS.discard(container_name)


def _cleanup_active_containers() -> None:
    with _ACTIVE_CONTAINERS_LOCK:
        container_names = sorted(_ACTIVE_CONTAINERS)
    for container_name in container_names:
        _force_remove_container(container_name)
        _untrack_active_container(container_name)


def _cleanup_on_signal(signum: int, frame) -> None:
    _emit(f"[e2e-parallel] received signal {signum}; cleaning up active docker shards")
    _cleanup_active_containers()
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
    atexit.register(_cleanup_active_containers)
    for signum in (signal.SIGINT, signal.SIGTERM):
        _PREVIOUS_SIGNAL_HANDLERS[signum] = signal.getsignal(signum)
        signal.signal(signum, _cleanup_on_signal)
    _CLEANUP_HOOKS_REGISTERED = True


def _build_image(image: str, dockerfile: str = _DEFAULT_DOCKERFILE) -> int:
    cmd = ["docker", "build", "-f", dockerfile, "-t", image, "."]
    _emit(f"[e2e-parallel] building docker image once: {shlex.join(cmd)}")
    return _run(cmd, log_path=LOG_DIR / "docker-build.log")


def _skip_build_requested(env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return source.get(_SKIP_BUILD_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _running_in_github_actions(env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return source.get("GITHUB_ACTIONS", "").strip().lower() == "true"


def _docker_image_exists(image: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        cwd=str(ROOT),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _prepare_image(
    image: str,
    *,
    dockerfile: str = _DEFAULT_DOCKERFILE,
    env: Mapping[str, str] | None = None,
) -> int:
    image_exists = _docker_image_exists(image)
    if image_exists and (_skip_build_requested(env) or _running_in_github_actions(env)):
        _emit(f"[e2e-parallel] reusing prebuilt docker image: {image}")
        return 0

    if _skip_build_requested(env):
        _emit(
            f"[e2e-parallel] {_SKIP_BUILD_ENV} requested skipping the docker build, "
            f"but image {image!r} is not present locally"
        )
        return 2

    build_rc = _build_image(image, dockerfile)
    if build_rc != 0:
        _emit(
            f"[e2e-parallel] docker build failed (exit {build_rc}); "
            f"log={LOG_DIR / 'docker-build.log'}"
        )
    return build_rc


def _api_snapshot(base_url: str, path: str) -> str:
    try:
        with urlopen(f"{base_url}{path}", timeout=5) as resp:
            payload = json.loads(resp.read())
        return json.dumps(payload, indent=2, sort_keys=True)
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return f"<unavailable: {exc}>"


def _wait_health(base_url: str, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{base_url}/api/health", timeout=2) as resp:
                if resp.status == 200:
                    return
        except (URLError, TimeoutError, OSError):
            pass
        time.sleep(0.5)
    raise RuntimeError("Container did not become healthy in time")


def _print_diagnostics(*, sim_log: Path, container_name: str, base_url: str) -> None:
    _emit("\n=== diagnostics: docker ps ===")
    subprocess.run(["docker", "ps", "-a"], cwd=str(ROOT), check=False)
    _emit("\n=== diagnostics: docker logs (tail 200) ===")
    subprocess.run(
        ["docker", "logs", "--tail", "200", container_name],
        cwd=str(ROOT),
        check=False,
    )
    _emit(
        f"\n=== diagnostics: /api/clients ===\n{_api_snapshot(base_url, '/api/clients')}"
    )
    _emit(
        f"\n=== diagnostics: /api/history ===\n{_api_snapshot(base_url, '/api/history')}"
    )
    if sim_log.exists():
        _emit(
            f"\n=== diagnostics: simulator log ===\n{sim_log.read_text(encoding='utf-8')}"
        )


def _run_shard_e2e(
    *,
    config: ShardConfig,
    marker: str,
    image: str,
    log_path: Path,
) -> int:
    """Run Docker e2e tests for one shard — replaces the old run_full_suite.py subprocess call."""
    base_url = f"http://127.0.0.1:{config.http_port}"
    data_dir = config.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "apps" / "server" / "data", data_dir, dirs_exist_ok=True)
    sim_log = data_dir / "sim_sender.log"
    container_started = False
    try:
        docker_run_cmd = [
            "docker",
            "run",
            "--detach",
            "--name",
            config.container_name,
            "--label",
            _SCOPE_LABEL,
            "--label",
            f"{_RUN_LABEL_KEY}={os.getpid()}",
            "-p",
            f"{config.http_port}:8000",
            "-p",
            f"{config.sim_data_port}:9000/udp",
            "-p",
            f"{config.sim_control_port}:9001/udp",
            "-v",
            f"{data_dir}:/app/apps/server/data",
            image,
        ]
        rc = _run(docker_run_cmd, log_path=log_path)
        if rc != 0:
            return rc
        container_started = True
        _track_active_container(config.container_name)
        _wait_health(base_url)
        env = os.environ.copy()
        env.update(
            {
                "VIBESENSOR_BASE_URL": base_url,
                "VIBESENSOR_SIM_SERVER_HOST": "127.0.0.1",
                "VIBESENSOR_SIM_DATA_PORT": str(config.sim_data_port),
                "VIBESENSOR_SIM_CONTROL_PORT": str(config.sim_control_port),
                "VIBESENSOR_SIM_CLIENT_CONTROL_BASE": str(
                    config.sim_client_control_base
                ),
                "VIBESENSOR_SIM_DURATION": "8",
                "VIBESENSOR_SIM_DURATION_LONG": "20",
                "VIBESENSOR_SIM_LOG": str(sim_log),
            }
        )
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
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"$ {shlex.join(pytest_cmd)}\n")
            proc = subprocess.run(
                pytest_cmd,
                cwd=str(ROOT),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
            )
            if proc.stdout:
                log_file.write(proc.stdout)
        return proc.returncode if proc.returncode is not None else 1
    except Exception:
        _print_diagnostics(
            sim_log=sim_log, container_name=config.container_name, base_url=base_url
        )
        raise
    finally:
        if container_started:
            _force_remove_container(config.container_name)
            _untrack_active_container(config.container_name)


def _shard_worker(
    *,
    config: ShardConfig,
    marker: str,
    image: str,
    results: dict[int, ShardResult],
    lock: threading.Lock,
) -> None:
    started = time.monotonic()
    rc = 1
    try:
        if not config.tests:
            _emit(
                f"[e2e-parallel] shard {config.index}/{config.count}: no tests selected; skipping"
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
                image=image,
                log_path=config.log_path,
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
        shutil.rmtree(config.data_dir, ignore_errors=True)
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
        description="Run docker-backed e2e tests in isolated parallel shards."
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
        "--docker-image",
        default="vibesensor-full-suite",
        help="Docker image name to build once and reuse across shards.",
    )
    parser.add_argument(
        "--dockerfile",
        default=_DEFAULT_DOCKERFILE,
        help="Dockerfile path for the shared e2e image build.",
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

    marker = args.pytest_marker
    if marker is None:
        marker = "e2e and not long_sim" if args.fast_e2e else "e2e"

    collected = collect_test_ids(["-m", marker, "apps/server/tests_e2e"])
    duration_cache_path = resolve_duration_cache_path(
        _DURATION_CACHE_ENV,
        "e2e-duration-cache.json",
        env=os.environ,
    )
    duration_cache = read_duration_cache(
        duration_cache_path,
        emit=_emit,
        label="e2e-parallel",
    )
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

    build_rc = _prepare_image(args.docker_image, dockerfile=args.dockerfile)
    if build_rc != 0:
        return build_rc

    _register_cleanup_hooks()
    pid = str(os.getpid())
    shards: list[ShardConfig] = []
    for shard_index in range(1, num_shards + 1):
        shards.append(
            ShardConfig(
                index=shard_index,
                count=num_shards,
                tests=shard_test_ids[shard_index - 1],
                container_name=f"vibesensor-e2e-shard-{pid}-{shard_index}",
                data_dir=Path(
                    tempfile.mkdtemp(prefix=f"vibesensor-e2e-shard-{shard_index}-")
                ),
                http_port=args.http_port_base + (shard_index - 1),
                sim_data_port=args.sim_data_port_base + (shard_index - 1),
                sim_control_port=args.sim_control_port_base + (shard_index - 1),
                sim_client_control_base=9100 + ((shard_index - 1) * 100),
                log_path=LOG_DIR / f"shard-{shard_index}.log",
                junit_path=LOG_DIR / f"shard-{shard_index}.xml",
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
                "image": args.docker_image,
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
            read_observed_durations_from_junit(
                shard.junit_path,
                shard.tests,
                emit=_emit,
                label="e2e-parallel",
            )
        )
    if observed_durations:
        merged_durations = merge_duration_observations(
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
