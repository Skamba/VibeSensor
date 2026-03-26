#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from pathlib import Path


def parse_collected_test_ids(
    output: str,
    *,
    normalize: Callable[[str], str | None],
) -> list[str]:
    test_ids: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if "::" not in line or line.startswith(("=", "<")):
            continue
        normalized = normalize(line)
        if normalized is not None:
            test_ids.append(normalized)
    return test_ids


def duration_cache_path(
    env_var: str,
    default_filename: str,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    source = os.environ if env is None else env
    raw_path = source.get(env_var, "").strip()
    if raw_path:
        return Path(raw_path).expanduser()
    return Path.home() / ".cache" / "vibesensor" / default_filename


def load_duration_cache(
    path: Path,
    *,
    emit: Callable[[str], None],
    label: str,
) -> dict[str, float]:
    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        emit(f"[{label}] ignoring unreadable duration cache: {path}")
        return {}
    if not isinstance(raw_payload, dict):
        emit(f"[{label}] ignoring invalid duration cache payload: {path}")
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


def merge_duration_observations(
    cached: Mapping[str, float],
    observed: Mapping[str, float],
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


def _junit_case_key(test_id: str) -> tuple[str, str]:
    path_part, *segments = test_id.split("::")
    normalized_path = path_part.removeprefix("apps/server/").removesuffix(".py")
    module_name = normalized_path.replace("/", ".")
    name = segments[-1] if segments else test_id
    classname_segments = [module_name, *segments[:-1]]
    return ".".join(segment for segment in classname_segments if segment), name


def observed_durations_from_junit(
    junit_path: Path,
    selected_tests: list[str],
    *,
    emit: Callable[[str], None],
    label: str,
) -> dict[str, float]:
    if not junit_path.exists():
        return {}
    try:
        root = ET.parse(junit_path).getroot()
    except (ET.ParseError, OSError):
        emit(f"[{label}] ignoring unreadable junit timings: {junit_path}")
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
