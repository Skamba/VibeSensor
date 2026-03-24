#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
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


def _parse_collected_test_ids(output: str) -> list[str]:
    test_ids: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if "::" not in line:
            continue
        if line.startswith("=") or line.startswith("<"):
            continue
        if line.startswith("tests/"):
            test_ids.append(f"apps/server/{line}")
            continue
        if line.startswith("apps/server/tests/") or line.startswith(
            "apps/server/tests_e2e/"
        ):
            test_ids.append(line)
            continue
        if line.startswith("tests_e2e/"):
            test_ids.append(f"apps/server/{line}")
    return test_ids


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
_SKIP_BUILD_ENV = "VIBESENSOR_E2E_SKIP_BUILD"


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


@dataclass(frozen=True)
class ShardResult:
    index: int
    return_code: int
    duration_s: float
    log_path: Path
    selected_tests: int


# Duration hints (seconds) for known slow fast-E2E tests.
# Tests exceeding SLOW_TEST_THRESHOLD get their own dedicated shard.
SLOW_TEST_THRESHOLD = 5.0
_DURATION_HINTS: dict[str, float] = {
    "test_e2e_docker_user_journeys.py::test_e2e_docker_user_journeys[clients_and_cars]": 17.1,
    "test_e2e_docker_edge_cases.py::test_logging_start_while_recording_rollover": 11.5,
    "test_e2e_docker_rear_left_wheel_fault.py::test_e2e_docker_rear_left_wheel_fault": 9.5,
    "test_e2e_docker_user_journeys.py::test_e2e_docker_user_journeys[language_pdf]": 8.9,
    "test_e2e_docker_user_journeys.py::test_e2e_docker_user_journeys[speed_export_delete]": 8.8,
    "test_e2e_docker_edge_cases.py::test_delete_active_run_returns_409_e2e": 5.8,
}
_DEFAULT_DURATION = 3.0


def _estimate_duration(test_id: str) -> float:
    """Return estimated duration for a test ID by matching against duration hints."""
    for hint_key, duration in _DURATION_HINTS.items():
        if hint_key in test_id:
            return duration
    return _DEFAULT_DURATION


def _assign_shards_by_duration(
    collected: list[str], min_shards: int
) -> list[list[str]]:
    """Assign tests to shards using duration-aware greedy bin-packing.

    Tests with estimated duration > SLOW_TEST_THRESHOLD get dedicated shards.
    Remaining tests are packed greedily into separate remainder shards.
    The total shard count is at least *min_shards*.
    """
    slow_tests: list[tuple[str, float]] = []
    fast_tests: list[tuple[str, float]] = []
    for test_id in collected:
        est = _estimate_duration(test_id)
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


def _build_image(image: str) -> int:
    cmd = ["docker", "build", "-f", "apps/server/Dockerfile", "-t", image, "."]
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


def _prepare_image(image: str, *, env: Mapping[str, str] | None = None) -> int:
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

    build_rc = _build_image(image)
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
            subprocess.run(
                ["docker", "rm", "-f", config.container_name],
                cwd=str(ROOT),
                check=False,
                capture_output=True,
            )


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
        default=2,
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

    shard_test_ids = _assign_shards_by_duration(collected, args.shards)
    num_shards = len(shard_test_ids)

    _emit(
        f"[e2e-parallel] collected {len(collected)} tests for marker '{marker}' "
        f"across {num_shards} shards (min requested: {args.shards})"
    )

    build_rc = _prepare_image(args.docker_image)
    if build_rc != 0:
        return build_rc

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
