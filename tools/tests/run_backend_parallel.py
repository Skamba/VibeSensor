#!/usr/bin/env python3
"""Run duration-balanced backend test shards with cached timing data."""

from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path


def _load_repo_tooling_support():
    helper_path = Path(__file__).resolve().parents[1] / "repo_tooling_support.py"
    spec = importlib.util.spec_from_file_location("repo_tooling_support", helper_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load repo tooling helpers from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_repo_tooling_support = _load_repo_tooling_support()
_parallel_runner_support = _repo_tooling_support.load_parallel_runner_support(__file__)
resolve_duration_cache_path = _parallel_runner_support.duration_cache_path
read_duration_cache = _parallel_runner_support.load_duration_cache
merge_duration_observations = _parallel_runner_support.merge_duration_observations
read_observed_durations_from_junit = (
    _parallel_runner_support.observed_durations_from_junit
)
collect_normalized_test_ids = _parallel_runner_support.parse_collected_test_ids


ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "artifacts" / "ai" / "logs" / "ci"
_DURATION_CACHE_ENV = "VIBESENSOR_BACKEND_DURATION_CACHE"
_XDIST_WORKERS_ENV = "VIBESENSOR_BACKEND_XDIST_WORKERS"
_DEFAULT_DURATION = 1.0
_DEFAULT_XDIST_WORKERS = 3


def _emit(line: str) -> None:
    print(line, flush=True)


def _normalize_collected_test_id(line: str) -> str | None:
    if line.startswith("tests/"):
        return f"apps/server/{line}"
    if line.startswith("apps/server/tests/"):
        return line
    return None


def _parse_collected_test_ids(output: str) -> list[str]:
    return collect_normalized_test_ids(output, normalize=_normalize_collected_test_id)


def _xdist_workers_default(env: Mapping[str, str] | None = None) -> int:
    source = os.environ if env is None else env
    raw = source.get(_XDIST_WORKERS_ENV)
    if raw is None or raw == "":
        return _DEFAULT_XDIST_WORKERS
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{_XDIST_WORKERS_ENV} must be an integer >= 0") from exc
    if value < 0:
        raise SystemExit(f"{_XDIST_WORKERS_ENV} must be >= 0")
    return value


def _duration_cache_path(env: Mapping[str, str] | None = None) -> Path:
    return resolve_duration_cache_path(
        _DURATION_CACHE_ENV,
        "backend-duration-cache.json",
        env=env,
    )


def _load_duration_cache(path: Path) -> dict[str, float]:
    return read_duration_cache(path, emit=_emit, label="backend-parallel")


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
        label="backend-parallel",
    )


def collect_test_ids(pytest_args: list[str]) -> list[str]:
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", *pytest_args]
    result = subprocess.run(
        cmd, check=False, capture_output=True, text=True, cwd=str(ROOT)
    )
    if result.returncode != 0:
        sys.stdout.write(result.stdout or "")
        sys.stderr.write(result.stderr or "")
        raise SystemExit(result.returncode)
    return _parse_collected_test_ids(result.stdout or "")


def _write_duration_cache(path: Path, durations: Mapping[str, float]) -> None:
    payload = {
        test_id: round(duration, 3)
        for test_id, duration in sorted(durations.items())
        if duration > 0
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"{json.dumps(payload, indent=2, sort_keys=True)}\n", encoding="utf-8"
    )


@contextmanager
def _locked_duration_cache(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(f"{path.suffix}.lock")
    with lock_path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _update_duration_cache(path: Path, observed: Mapping[str, float]) -> None:
    if not observed:
        return
    try:
        with _locked_duration_cache(path):
            cached = _load_duration_cache(path)
            merged = _merge_duration_observations(cached, observed)
            _write_duration_cache(path, merged)
    except OSError:
        _emit(f"[backend-parallel] failed to update duration cache: {path}")


def _group_tests_by_path(collected: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for test_id in collected:
        path = test_id.split("::", 1)[0]
        grouped[path].append(test_id)
    return dict(grouped)


def _estimate_target_duration(
    test_ids: list[str], durations: Mapping[str, float]
) -> float:
    return sum(durations.get(test_id, _DEFAULT_DURATION) for test_id in test_ids)


def _assign_shards_by_duration(
    collected: list[str], shard_count: int, durations: Mapping[str, float]
) -> list[list[str]]:
    """Assign whole test files to shards using duration-aware greedy bin-packing."""
    grouped = _group_tests_by_path(collected)
    weighted_targets = [
        (path, _estimate_target_duration(test_ids, durations))
        for path, test_ids in grouped.items()
    ]
    weighted_targets.sort(key=lambda item: (-item[1], item[0]))

    shard_targets: list[list[str]] = [[] for _ in range(shard_count)]
    shard_loads: list[float] = [0.0] * shard_count
    for path, duration in weighted_targets:
        index = min(
            range(shard_count), key=lambda shard_index: shard_loads[shard_index]
        )
        shard_targets[index].append(path)
        shard_loads[index] += duration
    return shard_targets


def _selected_test_ids(
    shard_targets: list[str], grouped_tests: Mapping[str, list[str]]
) -> list[str]:
    selected: list[str] = []
    for target in shard_targets:
        selected.extend(grouped_tests.get(target, []))
    return selected


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


def _write_empty_junit(path: Path) -> None:
    testsuite = ET.Element("testsuite", name="backend-tests", tests="0")
    ET.ElementTree(testsuite).write(path, encoding="utf-8", xml_declaration=True)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a duration-balanced shard of apps/server/tests."
    )
    parser.add_argument(
        "--shards",
        type=int,
        default=1,
        help="Total number of backend test shards.",
    )
    parser.add_argument(
        "--shard-index",
        type=int,
        default=1,
        help="1-based shard index to execute.",
    )
    parser.add_argument(
        "--junitxml",
        default=None,
        help="Optional JUnit XML output path for the selected shard.",
    )
    parser.add_argument(
        "--xdist-workers",
        type=int,
        default=_xdist_workers_default(),
        help=(
            "Intra-shard pytest-xdist worker count; defaults to "
            f"{_XDIST_WORKERS_ENV} or {_DEFAULT_XDIST_WORKERS}."
        ),
    )
    args = parser.parse_args(argv)
    if args.shards < 1:
        raise SystemExit("--shards must be >= 1")
    if not 1 <= args.shard_index <= args.shards:
        raise SystemExit("--shard-index must be between 1 and --shards")
    if args.xdist_workers < 0:
        raise SystemExit("--xdist-workers must be >= 0")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    collected = collect_test_ids(["apps/server/tests"])
    grouped_tests = _group_tests_by_path(collected)

    duration_cache_path = _duration_cache_path(os.environ)
    duration_cache = _load_duration_cache(duration_cache_path)
    if duration_cache:
        _emit(
            f"[backend-parallel] loaded {len(duration_cache)} cached test durations from "
            f"{duration_cache_path}"
        )

    shard_targets = _assign_shards_by_duration(collected, args.shards, duration_cache)
    selected_targets = shard_targets[args.shard_index - 1]
    selected_tests = _selected_test_ids(selected_targets, grouped_tests)

    junit_path = (
        Path(args.junitxml)
        if args.junitxml is not None
        else LOG_DIR / f"backend-tests-{args.shard_index}.xml"
    )
    log_path = junit_path.with_suffix(".log")
    junit_path.parent.mkdir(parents=True, exist_ok=True)

    _emit(
        f"[backend-parallel] collected {len(collected)} test cases across "
        f"{len(grouped_tests)} test files; running shard {args.shard_index}/{args.shards} "
        f"with {len(selected_targets)} files and {len(selected_tests)} test cases "
        f"using pytest -n {args.xdist_workers}"
    )

    if not selected_targets:
        _emit(
            f"[backend-parallel] shard {args.shard_index}/{args.shards}: no files selected; skipping"
        )
        _write_empty_junit(junit_path)
        return 0

    pytest_cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-n",
        str(args.xdist_workers),
        "--tb=short",
        "--junitxml",
        str(junit_path),
        *selected_targets,
    ]
    started = time.monotonic()
    rc = _run(pytest_cmd, log_path=log_path)
    elapsed = time.monotonic() - started

    observed_durations = _observed_durations_from_junit(junit_path, selected_tests)
    if observed_durations:
        _update_duration_cache(duration_cache_path, observed_durations)
        _emit(
            f"[backend-parallel] updated duration cache with {len(observed_durations)} observed "
            f"test timings at {duration_cache_path}"
        )

    if rc == 0:
        _emit(
            f"[backend-parallel] shard {args.shard_index}/{args.shards} passed in "
            f"{elapsed:.1f}s log={log_path}"
        )
        return 0

    _emit(
        f"[backend-parallel] shard {args.shard_index}/{args.shards} failed "
        f"(exit {rc}) in {elapsed:.1f}s tail:\n{_tail(log_path)}"
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
