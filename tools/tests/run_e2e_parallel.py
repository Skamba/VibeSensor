#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from pytest_shard import collect_test_ids

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "artifacts" / "ai" / "logs" / "e2e_parallel"
PRINT_LOCK = threading.Lock()


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


def _assign_shards_by_file(collected: list[str], shard_count: int) -> list[list[str]]:
    tests_by_file: dict[str, list[str]] = {}
    for test_id in collected:
        file_path = test_id.split("::", 1)[0]
        tests_by_file.setdefault(file_path, []).append(test_id)

    shard_tests: list[list[str]] = [[] for _ in range(shard_count)]
    shard_load: list[int] = [0 for _ in range(shard_count)]
    file_groups = sorted(
        tests_by_file.items(), key=lambda item: len(item[1]), reverse=True
    )
    for _, tests in file_groups:
        target = min(range(shard_count), key=lambda idx: shard_load[idx])
        shard_tests[target].extend(tests)
        shard_load[target] += len(tests)
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
    return int(proc.returncode)


def _tail(path: Path, lines: int = 60) -> str:
    if not path.exists():
        return "<missing log>"
    content = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(content[-lines:])


def _build_image(image: str) -> int:
    cmd = ["docker", "build", "-f", "apps/server/Dockerfile", "-t", image, "."]
    _emit(f"[e2e-parallel] building docker image once: {shlex.join(cmd)}")
    return _run(cmd, log_path=LOG_DIR / "docker-build.log")


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
            cmd = [
                sys.executable,
                "tools/tests/run_full_suite.py",
                "--skip-ui-sync",
                "--skip-ui-smoke",
                "--skip-unit-tests",
                "--skip-docker-build",
                "--docker-image",
                image,
                "--container-name",
                config.container_name,
                "--http-port",
                str(config.http_port),
                "--sim-data-port",
                str(config.sim_data_port),
                "--sim-control-port",
                str(config.sim_control_port),
                "--sim-client-control-base",
                str(config.sim_client_control_base),
                "--data-dir",
                str(config.data_dir),
                "--pytest-marker",
                marker,
            ]
            for test_id in config.tests:
                cmd.extend(["--pytest-target", test_id])
            _emit(
                f"[e2e-parallel] shard {config.index}/{config.count}: "
                f"tests={len(config.tests)} log={config.log_path}"
            )
            rc = _run(cmd, log_path=config.log_path)
            if rc != 0:
                _emit(
                    f"[e2e-parallel] shard {config.index}/{config.count} failed "
                    f"(exit {rc}) tail:\n{_tail(config.log_path)}"
                )
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
        "--shards", type=int, default=2, help="Number of parallel shards."
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
        default=18000,
        help="Base host HTTP port; shard N uses base + (N-1).",
    )
    parser.add_argument(
        "--sim-data-port-base",
        type=int,
        default=19000,
        help="Base host simulator UDP data port; shard N uses base + (N-1).",
    )
    parser.add_argument(
        "--sim-control-port-base",
        type=int,
        default=19100,
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
    _emit(
        f"[e2e-parallel] collected {len(collected)} tests for marker '{marker}' "
        f"across {args.shards} shards"
    )

    build_rc = _build_image(args.docker_image)
    if build_rc != 0:
        _emit(
            f"[e2e-parallel] docker build failed (exit {build_rc}); "
            f"log={LOG_DIR / 'docker-build.log'}"
        )
        return build_rc

    pid = str(os.getpid())
    shard_test_ids = _assign_shards_by_file(collected, args.shards)
    shards: list[ShardConfig] = []
    for shard_index in range(1, args.shards + 1):
        shards.append(
            ShardConfig(
                index=shard_index,
                count=args.shards,
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
    for shard_index in range(1, args.shards + 1):
        result = results[shard_index]
        if result.return_code == 0:
            _emit(
                f"- shard {result.index}/{args.shards}: PASS tests={result.selected_tests} "
                f"time={result.duration_s:.1f}s log={result.log_path}"
            )
            continue
        overall_ok = False
        _emit(
            f"- shard {result.index}/{args.shards}: FAIL tests={result.selected_tests} "
            f"exit={result.return_code} time={result.duration_s:.1f}s log={result.log_path}"
        )
    _emit(f"total wall time: {elapsed:.1f}s")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
