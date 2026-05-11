#!/usr/bin/env python3
"""Randomized fuzz harness for the diagnostics analysis engine.

Exercises the real ``summarize_run_data()`` entrypoint with realistic-but-varied
metadata and sample payloads. On failure, Hypothesis minimizes the case and this
script writes a JSON reproduction artifact under ``artifacts/fuzz/``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from fuzz_analysis_assertions import validate_summary
from fuzz_analysis_scenarios import (
    coerce_include_samples,
    materialize_samples,
    sample_case_strategy,
)
from fuzz_artifacts import write_analysis_failure_artifact
from fuzz_common import terminate_processes, worker_prefix, worker_seed

REPO_ROOT = Path(__file__).resolve().parents[2]


ARTIFACT_DIR = REPO_ROOT / "artifacts" / "fuzz"


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
        cmd.extend(["--seed", str(worker_seed(config.seed, worker_index))])
    if config.include_samples is True:
        cmd.append("--include-samples")
    elif config.include_samples is False:
        cmd.append("--no-include-samples")
    return cmd


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
    from vibesensor.shared.order_bands import vehicle_orders_hz
    from vibesensor.strength_bands import bucket_for_strength
    from vibesensor.vibration_strength import vibration_strength_db_scalar

    stop_event = threading.Event()
    start = time.monotonic()
    deadline = start + config.duration_s
    current_case: dict[str, object] | None = None
    current_summary: dict[str, object] | None = None
    total_examples = 0
    worker_index = config.worker_index if config.worker_index is not None else 0
    worker_seed_value = worker_seed(config.seed, worker_index)

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
    @given(case=sample_case_strategy(st))
    def _fuzz(case: dict[str, object]) -> None:
        nonlocal current_case, current_summary, total_examples
        total_examples += 1
        current_case = case
        current_summary = None
        samples = materialize_samples(
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
        include_samples = coerce_include_samples(case, config.include_samples)
        summary = summarize_run_data(
            dict(metadata),
            samples,
            lang=lang,
            include_samples=include_samples,
            file_name=f"{metadata.get('run_id', 'fuzz-run')}.jsonl",
        )
        current_summary = dict(summary)
        validate_summary(
            current_summary,
            expected_rows=len(samples),
            TypeAdapter=TypeAdapter,
            AnalysisSummary=AnalysisSummary,
        )

    if worker_seed_value is not None:
        _fuzz = seed(worker_seed_value)(_fuzz)

    try:
        while not stop_event.is_set() and time.monotonic() < deadline:
            _fuzz()
    except BaseException as exc:
        stop_event.set()
        artifact_path = write_analysis_failure_artifact(
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
    prefix = worker_prefix(config.worker_index)
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
                    terminate_processes(
                        [process for _, process, _ in processes],
                        repo_root=REPO_ROOT,
                    )
                    break
                if remaining:
                    time.sleep(0.2)
                pending = remaining
        finally:
            terminate_processes(
                [process for _, process, _ in processes],
                repo_root=REPO_ROOT,
            )

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
