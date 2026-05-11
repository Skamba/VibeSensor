#!/usr/bin/env python3
"""Randomized fuzz harnesses for the live FFT and signal-processing pipeline."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from fuzz_artifacts import write_processing_failure_artifact
from fuzz_common import terminate_processes, worker_prefix, worker_seed
from fuzz_processing_assertions import is_sorted_desc, json_no_nan
from fuzz_processing_scenarios import (
    fft_case_strategy,
    make_freq_slice,
    processor_case_strategy,
    strength_case_strategy,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


ARTIFACT_DIR = REPO_ROOT / "artifacts" / "fuzz"

TargetName = Literal["strength", "fft", "processor", "all"]


@dataclass(frozen=True)
class FuzzConfig:
    duration_s: float
    batch_examples: int
    processes: int
    seed: int | None
    target: TargetName
    artifact_dir: Path
    worker_index: int | None
    result_file: Path | None


def _parse_args() -> FuzzConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=("strength", "fft", "processor", "all"),
        default="all",
        help="Which fuzz target to run (default: all).",
    )
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
        help="Optional Hypothesis seed for repeatable runs.",
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
        target=args.target,
        artifact_dir=args.artifact_dir.resolve(),
        worker_index=args.worker_index,
        result_file=args.result_file.resolve()
        if args.result_file is not None
        else None,
    )


def _float_or_none(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _run_local_target(
    *,
    config: FuzzConfig,
    duration_s: float,
    worker_fn: Callable[[int, float, threading.Event], int],
) -> tuple[float, int]:
    start = time.monotonic()
    deadline = start + duration_s
    stop_event = threading.Event()
    worker_index = config.worker_index if config.worker_index is not None else 0
    total_examples = worker_fn(worker_index, deadline, stop_event)
    return time.monotonic() - start, total_examples


def _build_worker_command(
    config: FuzzConfig, *, worker_index: int, result_file: Path
) -> list[str]:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--target",
        config.target,
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
    return cmd


def _terminate_processes(processes: Sequence[subprocess.Popen[str]]) -> None:
    terminate_processes(processes, repo_root=REPO_ROOT)


def _run_strength_target(config: FuzzConfig, *, duration_s: float) -> dict[str, object]:
    from hypothesis import HealthCheck, Phase, given, seed, settings
    from hypothesis import strategies as st
    from pydantic import TypeAdapter

    from vibesensor.strength_bands import bucket_for_strength
    from vibesensor.vibration_strength import (
        VibrationStrengthMetrics,
        combined_spectrum_amp_g,
        compute_vibration_strength_db,
        noise_floor_amp_p20_g,
        peak_band_rms_amp_g,
        vibration_strength_db_scalar,
    )

    def _worker(worker_index: int, deadline: float, stop_event: threading.Event) -> int:
        current_case: dict[str, object] | None = None
        current_output: dict[str, object] | None = None
        worker_examples = 0
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
        @given(case=strength_case_strategy(st))
        def _fuzz(case: dict[str, object]) -> None:
            nonlocal current_case, current_output, worker_examples
            worker_examples += 1
            current_case = case
            current_output = None

            axis_spectra_raw = case["axis_spectra"]
            if not isinstance(axis_spectra_raw, Sequence):
                raise TypeError("axis_spectra must be a sequence")
            axis_spectra = [
                [float(value) for value in axis_values]
                for axis_values in axis_spectra_raw
                if isinstance(axis_values, Sequence)
            ]
            combined = combined_spectrum_amp_g(
                axis_spectra_amp_g=axis_spectra,
                axis_count_for_mean=(
                    int(case["axis_count_for_mean"])
                    if isinstance(case.get("axis_count_for_mean"), int)
                    else None
                ),
            )
            if combined:
                assert all(np.isfinite(combined)), (
                    "combined spectrum contains non-finite values"
                )
                assert all(value >= 0.0 for value in combined), (
                    "combined spectrum contains negatives"
                )

            floor_amp = noise_floor_amp_p20_g(combined_spectrum_amp_g=combined)
            assert np.isfinite(floor_amp) and floor_amp >= 0.0

            freq_hz = make_freq_slice(
                len(combined),
                start_hz=float(case["start_hz"]),
                step_hz=float(case["freq_step_hz"]),
            )
            if combined:
                center_idx = int(case["center_idx"])
                band_rms = peak_band_rms_amp_g(
                    freq_hz=freq_hz,
                    combined_spectrum_amp_g=combined,
                    center_idx=center_idx,
                    bandwidth_hz=float(case["bandwidth_hz"]),
                )
            else:
                band_rms = 0.0
            assert np.isfinite(band_rms) and band_rms >= 0.0

            scalar_db = vibration_strength_db_scalar(
                peak_band_rms_amp_g=band_rms,
                floor_amp_g=floor_amp,
                epsilon_g=_float_or_none(case.get("epsilon_g")),
            )
            assert np.isfinite(scalar_db)
            assert bucket_for_strength(float(scalar_db)).startswith("l")

            metrics = compute_vibration_strength_db(
                freq_hz=freq_hz,
                combined_spectrum_amp_g_values=combined,
                top_n=8,
            )
            current_output = {"combined": combined, "metrics": metrics}
            TypeAdapter(VibrationStrengthMetrics).validate_python(metrics)
            assert np.isfinite(float(metrics["vibration_strength_db"]))
            assert np.isfinite(float(metrics["noise_floor_amp_g"]))
            assert np.isfinite(float(metrics["peak_amp_g"]))
            peak_strengths = [
                float(peak["vibration_strength_db"])
                for peak in metrics["top_peaks"]
                if isinstance(peak, Mapping) and "vibration_strength_db" in peak
            ]
            assert is_sorted_desc(peak_strengths), (
                "strength peaks not sorted by descending dB"
            )
            json_no_nan(metrics)

        if worker_seed_value is not None:
            _fuzz = seed(worker_seed_value)(_fuzz)

        try:
            while not stop_event.is_set() and time.monotonic() < deadline:
                _fuzz()
        except BaseException as exc:
            stop_event.set()
            artifact_path = write_processing_failure_artifact(
                target="strength",
                case=current_case,
                output=current_output,
                exc=exc,
                artifact_dir=config.artifact_dir,
            )
            if artifact_path is not None:
                print(f"Failure artifact written to {artifact_path}")
            raise

        return worker_examples

    elapsed_s, total_examples = _run_local_target(
        config=config,
        duration_s=duration_s,
        worker_fn=_worker,
    )
    return {
        "target": "strength",
        "elapsed_s": elapsed_s,
        "examples": total_examples,
    }


def _run_fft_target(config: FuzzConfig, *, duration_s: float) -> dict[str, object]:
    from hypothesis import HealthCheck, Phase, given, seed, settings
    from hypothesis import strategies as st
    from pydantic import TypeAdapter

    from vibesensor.shared.fft_analysis import compute_fft_spectrum
    from vibesensor.shared.types.payload_types import AxisPeak
    from vibesensor.vibration_strength import VibrationStrengthMetrics

    def _worker(worker_index: int, deadline: float, stop_event: threading.Event) -> int:
        current_case: dict[str, object] | None = None
        current_output: dict[str, object] | None = None
        worker_examples = 0
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
        @given(case=fft_case_strategy(st))
        def _fuzz(case: dict[str, object]) -> None:
            nonlocal current_case, current_output, worker_examples
            worker_examples += 1
            current_case = case
            current_output = None

            sample_rate_hz = int(case["sample_rate_hz"])
            fft_n = int(case["fft_n"])
            block = np.asarray(case["base_block"], dtype=np.float32)
            block += np.float32(float(case["dc_offset"]))
            block[
                int(case["spike_axis"]),
                int(case["spike_col"]),
            ] += np.float32(float(case["spike_value"]))
            window = np.hanning(fft_n).astype(np.float32)
            scale = float(2.0 / max(1.0, float(np.sum(window))))
            freqs = np.fft.rfftfreq(fft_n, d=1.0 / sample_rate_hz)
            valid = (freqs >= float(case["spectrum_min_hz"])) & (
                freqs <= float(case["spectrum_max_hz"])
            )
            result = compute_fft_spectrum(
                block,
                sample_rate_hz,
                fft_window=window,
                fft_scale=scale,
                freq_slice=freqs[valid].astype(np.float32),
                valid_idx=np.flatnonzero(valid),
                spike_filter_enabled=bool(case["spike_filter_enabled"]),
            )

            current_output = {
                "freq_slice": result["freq_slice"].tolist(),
                "combined_amp": result["combined_amp"].tolist(),
                "axis_peaks": result["axis_peaks"],
                "strength_metrics": result["strength_metrics"],
            }

            freq_slice = result["freq_slice"]
            combined_amp = result["combined_amp"]
            assert freq_slice.ndim == 1
            assert combined_amp.ndim == 1
            assert freq_slice.size == combined_amp.size
            assert np.all(np.isfinite(freq_slice))
            assert np.all(np.isfinite(combined_amp))
            assert np.all(combined_amp >= 0.0)
            if freq_slice.size > 1:
                assert np.all(np.diff(freq_slice) >= 0.0), (
                    "frequency slice not monotonic"
                )
            for axis in ("x", "y", "z"):
                axis_payload = result["spectrum_by_axis"][axis]
                assert axis_payload["freq"].shape == freq_slice.shape
                assert axis_payload["amp"].shape == combined_amp.shape
                assert np.all(np.isfinite(axis_payload["amp"]))
                TypeAdapter(list[AxisPeak]).validate_python(result["axis_peaks"][axis])
            TypeAdapter(VibrationStrengthMetrics).validate_python(
                result["strength_metrics"]
            )
            json_no_nan(current_output)

        if worker_seed_value is not None:
            _fuzz = seed(worker_seed_value)(_fuzz)

        try:
            while not stop_event.is_set() and time.monotonic() < deadline:
                _fuzz()
        except BaseException as exc:
            stop_event.set()
            artifact_path = write_processing_failure_artifact(
                target="fft",
                case=current_case,
                output=current_output,
                exc=exc,
                artifact_dir=config.artifact_dir,
            )
            if artifact_path is not None:
                print(f"Failure artifact written to {artifact_path}")
            raise

        return worker_examples

    elapsed_s, total_examples = _run_local_target(
        config=config,
        duration_s=duration_s,
        worker_fn=_worker,
    )
    return {
        "target": "fft",
        "elapsed_s": elapsed_s,
        "examples": total_examples,
    }


def _run_processor_target(
    config: FuzzConfig, *, duration_s: float
) -> dict[str, object]:
    from hypothesis import HealthCheck, Phase, given, seed, settings
    from hypothesis import strategies as st
    from pydantic import TypeAdapter

    from vibesensor.infra.processing import SignalProcessor
    from vibesensor.shared.types.payload_types import (
        ClientMetrics,
        IntakeStatsPayload,
        SpectraPayload,
        SpectrumSeriesPayload,
        TimeAlignmentPayload,
    )

    def _worker(worker_index: int, deadline: float, stop_event: threading.Event) -> int:
        current_case: dict[str, object] | None = None
        current_output: dict[str, object] | None = None
        worker_examples = 0
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
        @given(case=processor_case_strategy(st))
        def _fuzz(case: dict[str, object]) -> None:
            nonlocal current_case, current_output, worker_examples
            worker_examples += 1
            current_case = case
            current_output = None

            processor = SignalProcessor(
                sample_rate_hz=int(case["sample_rate_hz"]),
                waveform_seconds=int(case["waveform_seconds"]),
                waveform_display_hz=int(case["waveform_display_hz"]),
                fft_n=int(case["fft_n"]),
                spectrum_min_hz=float(case["spectrum_min_hz"]),
                spectrum_max_hz=float(case["spectrum_max_hz"]),
                accel_scale_g_per_lsb=_float_or_none(case.get("accel_scale_g_per_lsb")),
            )

            clients_raw = case["clients"]
            chunks_raw = case["chunks"]
            if not isinstance(clients_raw, Sequence) or not isinstance(
                chunks_raw, Sequence
            ):
                raise TypeError(
                    "processor case must contain sequence clients and chunks"
                )
            clients = [str(client_id) for client_id in clients_raw]
            for chunk in chunks_raw:
                if not isinstance(chunk, Mapping):
                    continue
                rows = np.asarray(chunk["rows"], dtype=np.float32)
                processor.ingest(
                    str(chunk["client_id"]),
                    rows,
                    sample_rate_hz=(
                        int(chunk["sample_rate_hz"])
                        if isinstance(chunk.get("sample_rate_hz"), int)
                        else None
                    ),
                    t0_us=int(chunk["t0_us"])
                    if isinstance(chunk.get("t0_us"), int)
                    else None,
                )

            metrics_by_client: dict[str, ClientMetrics] = {}
            spectrum_by_client: dict[str, object] = {}
            latest_xyz: dict[str, object] = {}
            for client_id in clients:
                metrics = processor.compute_metrics(client_id)
                TypeAdapter(ClientMetrics).validate_python(metrics)
                json_no_nan(metrics)
                metrics_by_client[client_id] = metrics

                spectrum_payload = processor.spectrum_payload(client_id)
                TypeAdapter(SpectrumSeriesPayload).validate_python(spectrum_payload)
                json_no_nan(spectrum_payload)
                spectrum_by_client[client_id] = spectrum_payload

                xyz = processor.latest_sample_xyz(client_id)
                if xyz is not None:
                    assert all(np.isfinite(component) for component in xyz)
                latest_xyz[client_id] = xyz

            compute_all_result = processor.compute_all(clients)
            for metrics in compute_all_result.values():
                TypeAdapter(ClientMetrics).validate_python(metrics)
            json_no_nan(compute_all_result)

            multi = processor.multi_spectrum_payload(clients)
            TypeAdapter(SpectraPayload).validate_python(multi)
            json_no_nan(multi)

            time_alignment = processor.time_alignment_info(clients)
            TypeAdapter(TimeAlignmentPayload).validate_python(time_alignment)
            json_no_nan(time_alignment)

            intake_stats = processor.intake_stats()
            TypeAdapter(IntakeStatsPayload).validate_python(intake_stats)
            json_no_nan(intake_stats)

            fresh_clients = processor.clients_with_recent_data(clients, max_age_s=60.0)
            assert set(fresh_clients).issubset(set(clients))

            current_output = {
                "metrics_by_client": metrics_by_client,
                "spectrum_by_client": spectrum_by_client,
                "latest_xyz": latest_xyz,
                "compute_all_result": compute_all_result,
                "multi": multi,
                "time_alignment": time_alignment,
                "intake_stats": intake_stats,
                "fresh_clients": fresh_clients,
            }

        if worker_seed_value is not None:
            _fuzz = seed(worker_seed_value)(_fuzz)

        try:
            while not stop_event.is_set() and time.monotonic() < deadline:
                _fuzz()
        except BaseException as exc:
            stop_event.set()
            artifact_path = write_processing_failure_artifact(
                target="processor",
                case=current_case,
                output=current_output,
                exc=exc,
                artifact_dir=config.artifact_dir,
            )
            if artifact_path is not None:
                print(f"Failure artifact written to {artifact_path}")
            raise

        return worker_examples

    elapsed_s, total_examples = _run_local_target(
        config=config,
        duration_s=duration_s,
        worker_fn=_worker,
    )
    return {
        "target": "processor",
        "elapsed_s": elapsed_s,
        "examples": total_examples,
    }


def _print_target_summary(config: FuzzConfig, summary: Mapping[str, object]) -> None:
    prefix = worker_prefix(config.worker_index)
    print(
        f"{prefix}{str(summary['target']).capitalize()} fuzz passed: "
        f"{float(summary['elapsed_s']):.1f}s with {int(summary['examples'])} randomized examples "
        f"(seed={config.seed if config.seed is not None else 'auto'})."
    )


def _run_worker_main(config: FuzzConfig) -> list[dict[str, object]]:
    targets: list[TargetName]
    if config.target == "all":
        targets = ["strength", "fft", "processor"]
    else:
        targets = [config.target]

    target_duration_s = config.duration_s / max(1, len(targets))
    summaries: list[dict[str, object]] = []
    for target in targets:
        if target == "strength":
            summary = _run_strength_target(config, duration_s=target_duration_s)
        elif target == "fft":
            summary = _run_fft_target(config, duration_s=target_duration_s)
        else:
            summary = _run_processor_target(config, duration_s=target_duration_s)
        summaries.append(summary)
        _print_target_summary(config, summary)
    return summaries


def _run_process_coordinator(config: FuzzConfig) -> int:
    with tempfile.TemporaryDirectory(prefix="processing-fuzz-") as temp_dir:
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

        aggregate_examples: dict[str, int] = {}
        aggregate_elapsed: dict[str, float] = {}
        for worker_index, _, result_file in processes:
            if not result_file.exists():
                raise SystemExit(
                    f"Worker {worker_index} did not write a result summary."
                )
            payload = json.loads(result_file.read_text(encoding="utf-8"))
            for summary in payload.get("summaries", []):
                target = str(summary["target"])
                aggregate_examples[target] = aggregate_examples.get(target, 0) + int(
                    summary["examples"]
                )
                aggregate_elapsed[target] = max(
                    aggregate_elapsed.get(target, 0.0),
                    float(summary["elapsed_s"]),
                )

        for target in ("strength", "fft", "processor"):
            if target not in aggregate_examples:
                continue
            print(
                f"Aggregate {target} fuzz passed: "
                f"{aggregate_elapsed[target]:.1f}s per worker, "
                f"{aggregate_examples[target]} randomized examples across "
                f"{config.processes} processes."
            )
    return 0


def main() -> int:
    config = _parse_args()

    try:
        import hypothesis  # noqa: F401
    except (
        ImportError
    ) as exc:  # pragma: no cover - only exercised in missing-dev-deps envs
        raise SystemExit(
            "Missing Hypothesis. Install backend dev dependencies first with "
            '`make setup` or `.venv/bin/python -m pip install -e "./apps/server[dev]"`.'
        ) from exc

    if config.worker_index is None and config.processes > 1:
        return _run_process_coordinator(config)

    summaries = _run_worker_main(config)
    if config.result_file is not None:
        config.result_file.parent.mkdir(parents=True, exist_ok=True)
        config.result_file.write_text(
            json.dumps(
                {"worker_index": config.worker_index, "summaries": summaries}, indent=2
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
