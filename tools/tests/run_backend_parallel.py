#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
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

# Keep these duration-cache and JUnit helpers aligned with tools/tests/run_e2e_parallel.py.
# They stay local here so this standalone tool can run directly without package-path setup.


ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "artifacts" / "ai" / "logs" / "ci"
_DURATION_CACHE_ENV = "VIBESENSOR_BACKEND_DURATION_CACHE"
_DEFAULT_DURATION = 1.0


def _emit(line: str) -> None:
    print(line, flush=True)


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
        if line.startswith("apps/server/tests/"):
            test_ids.append(line)
    return test_ids


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


def _duration_cache_path(env: Mapping[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    raw_path = source.get(_DURATION_CACHE_ENV, "").strip()
    if raw_path:
        return Path(raw_path).expanduser()
    return Path.home() / ".cache" / "vibesensor" / "backend-duration-cache.json"


def _load_duration_cache(path: Path) -> dict[str, float]:
    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        _emit(f"[backend-parallel] ignoring unreadable duration cache: {path}")
        return {}
    if not isinstance(raw_payload, dict):
        _emit(f"[backend-parallel] ignoring invalid duration cache payload: {path}")
        return {}

    durations: dict[str, float] = {}
    for test_id, raw_duration in raw_payload.items():
        if not isinstance(test_id, str):
            continue
        try:
            duration = float(raw_duration)
        except (TypeError, ValueError):
            continue
        if duration > 0:
            durations[test_id] = duration
    return durations


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


def _merge_duration_observations(
    cached: Mapping[str, float], observed: Mapping[str, float]
) -> dict[str, float]:
    merged = dict(cached)
    for test_id, duration in observed.items():
        if duration <= 0:
            continue
        previous = merged.get(test_id)
        merged[test_id] = (
            duration if previous is None else round((previous + duration) / 2.0, 3)
        )
    return merged


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


def _junit_case_key(test_id: str) -> tuple[str, str]:
    path_part, *segments = test_id.split("::")
    normalized_path = path_part.removeprefix("apps/server/").removesuffix(".py")
    module_name = normalized_path.replace("/", ".")
    name = segments[-1] if segments else test_id
    classname_segments = [module_name, *segments[:-1]]
    return ".".join(segment for segment in classname_segments if segment), name


def _observed_durations_from_junit(
    junit_path: Path, selected_tests: list[str]
) -> dict[str, float]:
    if not junit_path.exists():
        return {}
    try:
        root = ET.parse(junit_path).getroot()
    except (ET.ParseError, OSError):
        _emit(f"[backend-parallel] ignoring unreadable junit timings: {junit_path}")
        return {}

    lookup = {_junit_case_key(test_id): test_id for test_id in selected_tests}
    observed: dict[str, float] = {}
    for case in root.iter("testcase"):
        classname = case.attrib.get("classname")
        name = case.attrib.get("name")
        raw_time = case.attrib.get("time")
        if not isinstance(classname, str) or not isinstance(name, str):
            continue
        if not isinstance(raw_time, str):
            continue
        test_id = lookup.get((classname, name))
        if test_id is None:
            continue
        try:
            duration = float(raw_time)
        except ValueError:
            continue
        if duration >= 0:
            observed[test_id] = duration
    return observed


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


def _parse_args() -> argparse.Namespace:
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
    args = parser.parse_args()
    if args.shards < 1:
        raise SystemExit("--shards must be >= 1")
    if not 1 <= args.shard_index <= args.shards:
        raise SystemExit("--shard-index must be between 1 and --shards")
    return args


def main() -> int:
    args = _parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    collected = collect_test_ids(["apps/server/tests"])
    grouped_tests = _group_tests_by_path(collected)

    duration_cache_path = _duration_cache_path()
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
        f"with {len(selected_targets)} files and {len(selected_tests)} test cases"
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
        "0",
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
