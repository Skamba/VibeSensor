#!/usr/bin/env python3
"""Randomized fuzz harness for the diagnostics analysis engine.

Exercises the real ``summarize_run_data()`` entrypoint with realistic-but-varied
metadata and sample payloads. On failure, Hypothesis minimizes the case and this
script writes a JSON reproduction artifact under ``artifacts/fuzz/``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_repo_tooling_support():
    helper_path = REPO_ROOT / "tools" / "repo_tooling_support.py"
    spec = importlib.util.spec_from_file_location("repo_tooling_support", helper_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load repo tooling helpers from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_repo_tooling_support = _load_repo_tooling_support()
ARTIFACT_DIR = REPO_ROOT / "artifacts" / "fuzz"

SENSOR_FIXTURES: tuple[dict[str, str], ...] = (
    {
        "client_id": "fl-wheel",
        "client_name": "Front Left Wheel",
        "location": "front_left_wheel",
    },
    {
        "client_id": "fr-wheel",
        "client_name": "Front Right Wheel",
        "location": "front_right_wheel",
    },
    {
        "client_id": "rl-wheel",
        "client_name": "Rear Left Wheel",
        "location": "rear_left_wheel",
    },
    {
        "client_id": "rr-wheel",
        "client_name": "Rear Right Wheel",
        "location": "rear_right_wheel",
    },
    {
        "client_id": "drive-tunnel",
        "client_name": "Driveshaft Tunnel",
        "location": "driveshaft_tunnel",
    },
    {
        "client_id": "engine-bay",
        "client_name": "Engine Bay",
        "location": "engine_bay",
    },
    {
        "client_id": "driver-seat",
        "client_name": "Driver Seat",
        "location": "driver_seat",
    },
)

SCENARIO_KINDS: tuple[str, ...] = (
    "idle",
    "steady",
    "accel",
    "decel",
    "oscillate",
)

FAULT_KINDS: tuple[str, ...] = (
    "none",
    "wheel",
    "driveline",
    "engine",
    "random",
)

LANGUAGE_CHOICES: tuple[str | None, ...] = (None, "en", "EN", "nl", "NL")
SENSOR_MODELS: tuple[str, ...] = ("ADXL345", "ICM-42688-P", "LSM6DSOX", "unknown")


@dataclass(frozen=True)
class FuzzConfig:
    duration_s: float
    batch_examples: int
    processes: int
    seed: int | None
    include_samples: bool | None
    artifact_dir: Path
    worker_index: int | None
    result_file: Path | None


def _parse_args() -> FuzzConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--duration-s",
        type=float,
        default=600.0,
        help="Total randomized fuzzing time budget in seconds (default: 600).",
    )
    parser.add_argument(
        "--batch-examples",
        type=int,
        default=200,
        help="Hypothesis examples per batch before checking the time budget (default: 200).",
    )
    parser.add_argument(
        "--processes",
        "--threads",
        dest="processes",
        type=int,
        default=16,
        help="Number of concurrent fuzz worker processes to run (default: 16).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional Hypothesis seed for a repeatable run.",
    )
    parser.add_argument(
        "--include-samples",
        dest="include_samples",
        action="store_true",
        help="Always serialize the samples list into the output summary.",
    )
    parser.add_argument(
        "--no-include-samples",
        dest="include_samples",
        action="store_false",
        help="Always omit the samples list from the output summary.",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ARTIFACT_DIR,
        help=f"Directory for minimized failure artifacts (default: {ARTIFACT_DIR}).",
    )
    parser.add_argument(
        "--worker-index", type=int, default=None, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--result-file", type=Path, default=None, help=argparse.SUPPRESS
    )
    parser.set_defaults(include_samples=None)
    args = parser.parse_args()
    if args.duration_s <= 0:
        parser.error("--duration-s must be positive")
    if args.batch_examples <= 0:
        parser.error("--batch-examples must be positive")
    if args.processes <= 0:
        parser.error("--processes must be positive")
    if args.worker_index is not None and args.worker_index < 0:
        parser.error("--worker-index must be non-negative")
    return FuzzConfig(
        duration_s=args.duration_s,
        batch_examples=args.batch_examples,
        processes=args.processes,
        seed=args.seed,
        include_samples=args.include_samples,
        artifact_dir=args.artifact_dir.resolve(),
        worker_index=args.worker_index,
        result_file=args.result_file.resolve()
        if args.result_file is not None
        else None,
    )


def _timestamp_at(offset_s: float) -> str:
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    return (base + timedelta(seconds=offset_s)).isoformat().replace("+00:00", "Z")


def _sample_rate_from_metadata(metadata: Mapping[str, object]) -> int | None:
    raw = metadata.get("raw_sample_rate_hz")
    return int(raw) if isinstance(raw, int) else None


def _coerce_include_samples(case: Mapping[str, object], override: bool | None) -> bool:
    if override is not None:
        return override
    raw = case.get("include_samples")
    return bool(raw) if isinstance(raw, bool) else False


def _metadata_strategy(st: Any) -> Any:
    positive_int = st.integers(min_value=32, max_value=6400)
    positive_float = st.floats(
        min_value=0.05, max_value=2.0, allow_nan=False, allow_infinity=False
    )
    settings_float = st.floats(
        min_value=0.1,
        max_value=10.0,
        allow_nan=False,
        allow_infinity=False,
    )
    return st.fixed_dictionaries(
        {
            "run_id": st.from_regex(r"[a-z0-9][a-z0-9_-]{2,20}", fullmatch=True),
            "start_time_utc": st.just(_timestamp_at(0.0)),
            "end_time_utc": st.one_of(
                st.none(),
                st.just(_timestamp_at(60.0)),
                st.just(_timestamp_at(180.0)),
            ),
            "sensor_model": st.sampled_from(SENSOR_MODELS),
            "raw_sample_rate_hz": st.one_of(st.none(), positive_int, st.just(0)),
            "feature_interval_s": st.one_of(st.none(), positive_float),
            "fft_window_size_samples": st.one_of(
                st.none(),
                st.sampled_from((128, 256, 512, 1024, 2048, 4096)),
            ),
            "accel_scale_g_per_lsb": st.one_of(
                st.none(),
                st.floats(
                    min_value=1e-5,
                    max_value=0.05,
                    allow_nan=False,
                    allow_infinity=False,
                ),
            ),
            "language": st.one_of(st.none(), st.sampled_from(("en", "nl", "EN", "NL"))),
            "incomplete_for_order_analysis": st.booleans(),
            "tire_width_mm": st.floats(
                min_value=100.0,
                max_value=355.0,
                allow_nan=False,
                allow_infinity=False,
            ),
            "tire_aspect_pct": st.floats(
                min_value=25.0,
                max_value=80.0,
                allow_nan=False,
                allow_infinity=False,
            ),
            "rim_in": st.floats(
                min_value=13.0,
                max_value=24.0,
                allow_nan=False,
                allow_infinity=False,
            ),
            "final_drive_ratio": settings_float,
            "current_gear_ratio": st.floats(
                min_value=0.4,
                max_value=4.8,
                allow_nan=False,
                allow_infinity=False,
            ),
        }
    )


def _sensor_selection_strategy(st: Any) -> Any:
    return st.lists(
        st.sampled_from(SENSOR_FIXTURES),
        min_size=1,
        max_size=4,
        unique_by=lambda sensor: sensor["client_id"],
    )


def _speed_for_step(
    kind: str,
    step: int,
    total_steps: int,
    low_kmh: float,
    high_kmh: float,
) -> float:
    if total_steps <= 1:
        return low_kmh
    ratio = step / float(total_steps - 1)
    if kind == "idle":
        return 0.0
    if kind == "steady":
        return low_kmh
    if kind == "accel":
        return low_kmh + ((high_kmh - low_kmh) * ratio)
    if kind == "decel":
        return high_kmh - ((high_kmh - low_kmh) * ratio)
    midpoint = 0.5
    swing = abs(ratio - midpoint) / midpoint
    return low_kmh + ((high_kmh - low_kmh) * (1.0 - swing))


def _build_peak(
    *,
    hz: float,
    amp_g: float,
    vibration_strength_db_scalar: Any,
    bucket_for_strength: Any,
    floor_amp_g: float,
) -> dict[str, float | str]:
    strength_db = vibration_strength_db_scalar(
        peak_band_rms_amp_g=amp_g,
        floor_amp_g=floor_amp_g,
    )
    return {
        "hz": round(max(0.1, hz), 3),
        "amp": round(max(1e-6, amp_g), 6),
        "vibration_strength_db": round(strength_db, 3),
        "strength_bucket": bucket_for_strength(strength_db),
    }


def _order_hz_for_fault(
    *,
    fault_kind: str,
    speed_kmh: float | None,
    metadata: Mapping[str, object],
    AnalysisSettingsSnapshot: Any,
    vehicle_orders_hz: Any,
) -> float | None:
    if speed_kmh is None or speed_kmh <= 0.0:
        return None
    settings = AnalysisSettingsSnapshot.from_dict(metadata)
    order_refs = vehicle_orders_hz(speed_mps=speed_kmh / 3.6, settings=settings)
    if not isinstance(order_refs, Mapping):
        return None
    if fault_kind == "wheel":
        value = order_refs.get("wheel_hz")
        return float(value) if isinstance(value, (int, float)) else None
    if fault_kind == "driveline":
        value = order_refs.get("drive_hz")
        return float(value) if isinstance(value, (int, float)) else None
    if fault_kind == "engine":
        value = order_refs.get("engine_hz")
        return float(value) if isinstance(value, (int, float)) else None
    return None


def _sample_case_strategy(st: Any) -> Any:
    @st.composite
    def _build(draw: Any) -> dict[str, object]:
        metadata = draw(_metadata_strategy(st))
        sensors = draw(_sensor_selection_strategy(st))
        scenario = draw(st.sampled_from(SCENARIO_KINDS))
        fault_kind = draw(st.sampled_from(FAULT_KINDS))
        include_samples = draw(st.booleans())
        lang = draw(st.sampled_from(LANGUAGE_CHOICES))
        steps = draw(st.integers(min_value=0, max_value=28))
        dt_s = draw(
            st.floats(
                min_value=0.2,
                max_value=2.5,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        low_speed = draw(
            st.floats(
                min_value=10.0,
                max_value=90.0,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        high_speed = draw(
            st.floats(
                min_value=max(low_speed + 5.0, 20.0),
                max_value=180.0,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        floor_amp_g = draw(
            st.floats(
                min_value=0.0005,
                max_value=0.05,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        base_fault_amp_g = draw(
            st.floats(
                min_value=0.002,
                max_value=0.4,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        diffuse_excitation = draw(st.booleans())
        missing_speed_ratio = draw(
            st.floats(
                min_value=0.0,
                max_value=0.7,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        blank_location_ratio = draw(
            st.floats(
                min_value=0.0,
                max_value=0.5,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        drop_counter = draw(st.integers(min_value=0, max_value=100))
        overflow_counter = draw(st.integers(min_value=0, max_value=30))
        accel_scale = draw(
            st.floats(
                min_value=0.005,
                max_value=0.35,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        background_hz = draw(
            st.floats(
                min_value=8.0,
                max_value=120.0,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        clutter_hz = draw(
            st.floats(
                min_value=20.0,
                max_value=250.0,
                allow_nan=False,
                allow_infinity=False,
            )
        )

        return {
            "metadata": metadata,
            "sensors": sensors,
            "scenario": scenario,
            "fault_kind": fault_kind,
            "include_samples": include_samples,
            "lang": lang,
            "steps": steps,
            "dt_s": dt_s,
            "low_speed": low_speed,
            "high_speed": high_speed,
            "floor_amp_g": floor_amp_g,
            "base_fault_amp_g": base_fault_amp_g,
            "diffuse_excitation": diffuse_excitation,
            "missing_speed_ratio": missing_speed_ratio,
            "blank_location_ratio": blank_location_ratio,
            "drop_counter": drop_counter,
            "overflow_counter": overflow_counter,
            "accel_scale": accel_scale,
            "background_hz": background_hz,
            "clutter_hz": clutter_hz,
        }

    return _build()


def _materialize_samples(
    case: Mapping[str, object],
    *,
    vibration_strength_db_scalar: Any,
    bucket_for_strength: Any,
    AnalysisSettingsSnapshot: Any,
    vehicle_orders_hz: Any,
) -> list[dict[str, object]]:
    metadata = case["metadata"]
    if not isinstance(metadata, Mapping):
        raise TypeError("case metadata must be a mapping")
    sensors = case["sensors"]
    if not isinstance(sensors, Sequence):
        raise TypeError("case sensors must be a sequence")

    scenario = str(case["scenario"])
    fault_kind = str(case["fault_kind"])
    steps = int(case["steps"])
    dt_s = float(case["dt_s"])
    low_speed = float(case["low_speed"])
    high_speed = float(case["high_speed"])
    floor_amp_g = float(case["floor_amp_g"])
    base_fault_amp_g = float(case["base_fault_amp_g"])
    diffuse_excitation = bool(case["diffuse_excitation"])
    missing_speed_ratio = float(case["missing_speed_ratio"])
    blank_location_ratio = float(case["blank_location_ratio"])
    drop_counter = int(case["drop_counter"])
    overflow_counter = int(case["overflow_counter"])
    accel_scale = float(case["accel_scale"])
    background_hz = float(case["background_hz"])
    clutter_hz = float(case["clutter_hz"])
    raw_sample_rate_hz = _sample_rate_from_metadata(metadata)

    samples: list[dict[str, object]] = []
    for step in range(steps):
        speed_kmh = _speed_for_step(scenario, step, steps, low_speed, high_speed)
        if steps > 0 and (step / max(1, steps)) < missing_speed_ratio:
            sampled_speed_kmh: float | None = None
        else:
            sampled_speed_kmh = round(speed_kmh, 3)

        fault_hz = _order_hz_for_fault(
            fault_kind=fault_kind,
            speed_kmh=sampled_speed_kmh,
            metadata=metadata,
            AnalysisSettingsSnapshot=AnalysisSettingsSnapshot,
            vehicle_orders_hz=vehicle_orders_hz,
        )
        timestamp_offset = step * dt_s

        for sensor_index, sensor in enumerate(sensors):
            if not isinstance(sensor, Mapping):
                continue
            dominance = 1.0
            if fault_kind != "none" and not diffuse_excitation:
                dominance = (
                    1.65 if sensor_index == 0 else (0.55 + (sensor_index * 0.12))
                )

            base_amp_g = max(1e-6, floor_amp_g * (1.2 + (sensor_index * 0.18)))
            fault_amp_g = max(1e-6, base_fault_amp_g * dominance)
            if fault_kind == "none":
                fault_amp_g = base_amp_g * 1.35

            if scenario == "idle":
                fault_amp_g *= 0.65

            vibration_strength_db = vibration_strength_db_scalar(
                peak_band_rms_amp_g=max(base_amp_g, fault_amp_g),
                floor_amp_g=floor_amp_g,
            )
            peaks = [
                _build_peak(
                    hz=fault_hz or background_hz,
                    amp_g=max(base_amp_g, fault_amp_g),
                    vibration_strength_db_scalar=vibration_strength_db_scalar,
                    bucket_for_strength=bucket_for_strength,
                    floor_amp_g=floor_amp_g,
                ),
                _build_peak(
                    hz=background_hz + (sensor_index * 3.0) + (step % 5),
                    amp_g=max(1e-6, base_amp_g * 0.85),
                    vibration_strength_db_scalar=vibration_strength_db_scalar,
                    bucket_for_strength=bucket_for_strength,
                    floor_amp_g=floor_amp_g,
                ),
                _build_peak(
                    hz=clutter_hz + (sensor_index * 1.5),
                    amp_g=max(1e-6, base_amp_g * 0.45),
                    vibration_strength_db_scalar=vibration_strength_db_scalar,
                    bucket_for_strength=bucket_for_strength,
                    floor_amp_g=floor_amp_g,
                ),
            ]

            sample: dict[str, object] = {
                "run_id": str(metadata.get("run_id") or ""),
                "timestamp_utc": _timestamp_at(timestamp_offset),
                "t_s": round(timestamp_offset, 3),
                "client_id": str(sensor.get("client_id") or ""),
                "client_name": str(sensor.get("client_name") or ""),
                "location": (
                    ""
                    if (sensor_index / max(1, len(sensors))) < blank_location_ratio
                    else str(sensor.get("location") or "")
                ),
                "sample_rate_hz": raw_sample_rate_hz,
                "speed_kmh": sampled_speed_kmh,
                "gps_speed_kmh": sampled_speed_kmh,
                "speed_source": "gps" if sampled_speed_kmh is not None else "none",
                "engine_rpm": (
                    round((sampled_speed_kmh or 0.0) * 35.0, 3)
                    if fault_kind == "engine" and sampled_speed_kmh is not None
                    else None
                ),
                "engine_rpm_source": (
                    "estimated_from_speed_and_ratios"
                    if fault_kind == "engine" and sampled_speed_kmh is not None
                    else "missing"
                ),
                "gear": float(metadata.get("current_gear_ratio") or 0.0) or None,
                "final_drive_ratio": float(metadata.get("final_drive_ratio") or 0.0)
                or None,
                "accel_x_g": round(base_amp_g * (0.8 + accel_scale), 6),
                "accel_y_g": round(base_amp_g * (0.6 + (accel_scale * 0.5)), 6),
                "accel_z_g": round(1.0 + base_amp_g * (0.4 + accel_scale), 6),
                "dominant_freq_hz": round(fault_hz or background_hz, 3),
                "dominant_axis": "combined",
                "top_peaks": peaks,
                "vibration_strength_db": round(vibration_strength_db, 3),
                "strength_bucket": bucket_for_strength(vibration_strength_db),
                "strength_peak_amp_g": round(max(base_amp_g, fault_amp_g), 6),
                "strength_floor_amp_g": round(floor_amp_g, 6),
                "frames_dropped_total": drop_counter + step,
                "queue_overflow_drops": overflow_counter + (step // 3),
            }
            samples.append(sample)
    return samples


def _validate_summary(
    summary: Mapping[str, object],
    expected_rows: int,
    TypeAdapter: Any,
    AnalysisSummary: Any,
) -> None:
    TypeAdapter(AnalysisSummary).validate_python(summary)
    summary_rows = summary.get("rows")
    if summary_rows != expected_rows:
        raise AssertionError(
            f"summary rows {summary_rows!r} != expected {expected_rows}"
        )
    if summary.get("findings") is None:
        raise AssertionError("summary findings missing")
    if summary.get("run_suitability") is None:
        raise AssertionError("summary run_suitability missing")
    json.dumps(summary, ensure_ascii=False, allow_nan=False)


def _write_failure_artifact(
    *,
    case: Mapping[str, object] | None,
    summary: Mapping[str, object] | None,
    exc: BaseException,
    artifact_dir: Path,
) -> Path | None:
    if case is None:
        return None
    artifact_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = "unknown-run"
    metadata = case.get("metadata")
    if isinstance(metadata, Mapping):
        raw_run_id = metadata.get("run_id")
        if isinstance(raw_run_id, str) and raw_run_id.strip():
            run_id = raw_run_id.strip()
    artifact_path = artifact_dir / (
        f"analysis-fuzz-failure-{timestamp}-{os.getpid()}-{run_id}.json"
    )
    payload: dict[str, object] = {
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "traceback": traceback.format_exc(),
        "case": case,
        "summary": summary,
    }
    artifact_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    return artifact_path


def _worker_seed(base_seed: int | None, worker_index: int) -> int | None:
    if base_seed is None:
        return None
    return base_seed + worker_index


def _worker_prefix(worker_index: int | None) -> str:
    if worker_index is None:
        return ""
    return f"[worker {worker_index}] "


def _build_worker_command(
    config: FuzzConfig, *, worker_index: int, result_file: Path
) -> list[str]:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--duration-s",
        str(config.duration_s),
        "--batch-examples",
        str(config.batch_examples),
        "--processes",
        "1",
        "--artifact-dir",
        str(config.artifact_dir),
        "--worker-index",
        str(worker_index),
        "--result-file",
        str(result_file),
    ]
    if config.seed is not None:
        cmd.extend(["--seed", str(_worker_seed(config.seed, worker_index))])
    if config.include_samples is True:
        cmd.append("--include-samples")
    elif config.include_samples is False:
        cmd.append("--no-include-samples")
    return cmd


def _terminate_processes(processes: Sequence[subprocess.Popen[str]]) -> None:
    _repo_tooling_support.terminate_processes(processes)


def _run_worker_main(config: FuzzConfig) -> dict[str, object]:
    try:
        from hypothesis import HealthCheck, Phase, given, seed, settings
        from hypothesis import strategies as st
    except (
        ImportError
    ) as exc:  # pragma: no cover - exercised only in missing-dev-deps envs
        raise SystemExit(
            "Missing Hypothesis. Install backend dev dependencies first with "
            '`make setup` or `.venv/bin/python -m pip install -e "./apps/server[dev]"`.'
        ) from exc

    from pydantic import TypeAdapter

    from vibesensor.adapters.analysis_summary import summarize_run_data
    from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
    from vibesensor.shared.types.history_analysis_contracts import AnalysisSummary
    from vibesensor.strength_bands import bucket_for_strength
    from vibesensor.use_cases.diagnostics import vehicle_orders_hz
    from vibesensor.vibration_strength import vibration_strength_db_scalar

    stop_event = threading.Event()
    start = time.monotonic()
    deadline = start + config.duration_s
    current_case: dict[str, object] | None = None
    current_summary: dict[str, object] | None = None
    total_examples = 0
    worker_index = config.worker_index if config.worker_index is not None else 0
    worker_seed = _worker_seed(config.seed, worker_index)

    @settings(
        max_examples=config.batch_examples,
        deadline=None,
        print_blob=True,
        database=None,
        suppress_health_check=(
            HealthCheck.too_slow,
            HealthCheck.data_too_large,
            HealthCheck.filter_too_much,
        ),
        phases=(Phase.generate, Phase.target, Phase.shrink),
    )
    @given(case=_sample_case_strategy(st))
    def _fuzz(case: dict[str, object]) -> None:
        nonlocal current_case, current_summary, total_examples
        total_examples += 1
        current_case = case
        current_summary = None
        samples = _materialize_samples(
            case,
            vibration_strength_db_scalar=vibration_strength_db_scalar,
            bucket_for_strength=bucket_for_strength,
            AnalysisSettingsSnapshot=AnalysisSettingsSnapshot,
            vehicle_orders_hz=vehicle_orders_hz,
        )
        case_with_samples = dict(case)
        case_with_samples["samples"] = samples
        current_case = case_with_samples
        metadata = case.get("metadata")
        if not isinstance(metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        lang = case.get("lang")
        if lang is not None and not isinstance(lang, str):
            raise TypeError("lang must be a string or None")
        include_samples = _coerce_include_samples(case, config.include_samples)
        summary = summarize_run_data(
            dict(metadata),
            samples,
            lang=lang,
            include_samples=include_samples,
            file_name=f"{metadata.get('run_id', 'fuzz-run')}.jsonl",
        )
        current_summary = dict(summary)
        _validate_summary(
            current_summary,
            expected_rows=len(samples),
            TypeAdapter=TypeAdapter,
            AnalysisSummary=AnalysisSummary,
        )

    if worker_seed is not None:
        _fuzz = seed(worker_seed)(_fuzz)

    try:
        while not stop_event.is_set() and time.monotonic() < deadline:
            _fuzz()
    except BaseException as exc:
        stop_event.set()
        artifact_path = _write_failure_artifact(
            case=current_case,
            summary=current_summary,
            exc=exc,
            artifact_dir=config.artifact_dir,
        )
        if artifact_path is not None:
            print(f"Failure artifact written to {artifact_path}")
        raise

    elapsed_s = time.monotonic() - start
    summary = {
        "target": "analysis",
        "elapsed_s": elapsed_s,
        "examples": total_examples,
    }
    prefix = _worker_prefix(config.worker_index)
    print(
        f"{prefix}Fuzz run passed: "
        f"{elapsed_s:.1f}s against summarize_run_data() "
        f"with {total_examples} randomized examples "
        f"(seed={config.seed if config.seed is not None else 'auto'})."
    )
    return summary


def _run_process_coordinator(config: FuzzConfig) -> int:
    with tempfile.TemporaryDirectory(prefix="analysis-fuzz-") as temp_dir:
        processes: list[tuple[int, subprocess.Popen[str], Path]] = []
        for worker_index in range(config.processes):
            result_file = Path(temp_dir) / f"worker-{worker_index}.json"
            process = subprocess.Popen(
                _build_worker_command(
                    config, worker_index=worker_index, result_file=result_file
                ),
                cwd=REPO_ROOT,
            )
            processes.append((worker_index, process, result_file))

        failure: tuple[int, int] | None = None
        try:
            pending = list(processes)
            while pending:
                remaining: list[tuple[int, subprocess.Popen[str], Path]] = []
                for worker_index, process, result_file in pending:
                    exit_code = process.poll()
                    if exit_code is None:
                        remaining.append((worker_index, process, result_file))
                        continue
                    if exit_code != 0 and failure is None:
                        failure = (worker_index, exit_code)
                if failure is not None:
                    _terminate_processes([process for _, process, _ in processes])
                    break
                if remaining:
                    time.sleep(0.2)
                pending = remaining
        finally:
            _terminate_processes([process for _, process, _ in processes])

        if failure is not None:
            worker_index, exit_code = failure
            raise SystemExit(f"Worker {worker_index} exited with code {exit_code}.")

        aggregate_examples = 0
        aggregate_elapsed = 0.0
        for worker_index, _, result_file in processes:
            if not result_file.exists():
                raise SystemExit(
                    f"Worker {worker_index} did not write a result summary."
                )
            payload = json.loads(result_file.read_text(encoding="utf-8"))
            aggregate_examples += int(payload["examples"])
            aggregate_elapsed = max(aggregate_elapsed, float(payload["elapsed_s"]))

        print(
            "Aggregate analysis fuzz passed: "
            f"{aggregate_elapsed:.1f}s per worker, "
            f"{aggregate_examples} randomized examples across {config.processes} processes."
        )
    return 0


def main() -> int:
    config = _parse_args()
    if config.worker_index is None and config.processes > 1:
        return _run_process_coordinator(config)

    summary = _run_worker_main(config)
    if config.result_file is not None:
        config.result_file.parent.mkdir(parents=True, exist_ok=True)
        config.result_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
