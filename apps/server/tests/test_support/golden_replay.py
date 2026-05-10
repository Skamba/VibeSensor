"""Generated golden replay fixtures for dense post-run regression tests."""

from __future__ import annotations

import json
import tracemalloc
from collections.abc import Mapping
from dataclasses import dataclass
from math import pi
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, cast

import numpy as np

from test_support.core import ALL_SENSORS, FINAL_DRIVE, GEAR_RATIO, standard_metadata
from test_support.sample_scenarios import make_sample
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.raw_capture import (
    RawCaptureChunkIndex,
    RawCaptureManifest,
    RawCaptureSensorClockSync,
    RawCaptureSensorData,
    RawCaptureSensorManifest,
    RawRunCapture,
)
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.shared.types.whole_run_analysis import WholeRunArtifactManifest
from vibesensor.use_cases.run.post_analysis_executor import (
    PostAnalysisExecutionConfig,
    execute_post_analysis,
)
from vibesensor.use_cases.run.post_analysis_input import PostAnalysisRunInput
from vibesensor.use_cases.run.post_analysis_loader import LoadedPostAnalysisRun
from vibesensor.use_cases.run.post_analysis_outcomes import PostAnalysisExecutionSuccess
from vibesensor.use_cases.run.post_analysis_summary import build_post_analysis_summary

GoldenUnavailableReason = Literal["missing_speed", "missing_rpm"]
GoldenScenarioGroup = Literal[
    "baseline",
    "wheel",
    "driveline",
    "engine",
    "resonance",
    "road_shock",
    "transient",
    "data_quality",
]

_RUN_START_US = 1_000_000
_SAMPLE_RATE_HZ = 256
_FFT_WINDOW_SIZE_SAMPLES = 256
_DEFAULT_DURATION_S = 8.0
_DEFAULT_SPEED_KMH = 80.0
_DEFAULT_ENGINE_RPM = 1500.0
_RAW_ACCEL_SCALE_G_PER_LSB = 0.001
_NOISE_FREQS_HZ = (37.0, 55.0)
_DRIVESHAFT_SOURCE = "driveline"
_ENGINE_SOURCE = "engine"
_WHEEL_SOURCE = "wheel/tire"


@dataclass(frozen=True, slots=True)
class GoldenReplayExpected:
    """Stable assertions attached to one generated replay fixture."""

    suspected_source: str | None
    strongest_location: str | None = None
    confidence_range: tuple[float, float] = (0.0, 1.0)
    confidence_label_key: str | None = None
    unavailable_reasons: tuple[GoldenUnavailableReason, ...] = ()
    tolerance_bands: Mapping[str, tuple[float, float]] | None = None
    max_false_positive_confidence: float | None = None
    required_warning_codes: tuple[str, ...] = ()
    required_metadata_minimums: Mapping[str, float] | None = None


@dataclass(frozen=True, slots=True)
class GoldenReplayFixture:
    """Compact fixture format; all raw waveform and summary rows are generated."""

    case_id: str
    title: str
    group: GoldenScenarioGroup
    seed: int
    expected: GoldenReplayExpected
    primary_frequency_hz: float | None = None
    strongest_sensor: str | None = None
    signal_amp_g: float = 0.08
    transfer_amp_g: float = 0.024
    speed_kmh: float | None = _DEFAULT_SPEED_KMH
    speed_sweep_kmh: tuple[float, float] | None = None
    speed_source: str = "gps"
    engine_rpm: float | None = _DEFAULT_ENGINE_RPM
    final_drive_ratio: float | None = FINAL_DRIVE
    current_gear_ratio: float | None = GEAR_RATIO
    duration_s: float = _DEFAULT_DURATION_S
    sample_rate_hz: int = _SAMPLE_RATE_HZ
    fft_window_size_samples: int = _FFT_WINDOW_SIZE_SAMPLES
    transient_duration_s: float = 0.0
    transient_frequency_hz: float | None = None
    fast_ci: bool = True

    def build(self, *, duration_s: float | None = None) -> GoldenReplayRun:
        run_id = f"golden-{self.case_id}"
        actual_duration_s = self.duration_s if duration_s is None else duration_s
        metadata = _metadata_for_fixture(self, run_id=run_id)
        samples = _summary_samples(self, run_id=run_id, duration_s=actual_duration_s)
        raw_capture = _raw_capture_for_fixture(self, run_id=run_id, duration_s=actual_duration_s)
        return GoldenReplayRun(
            fixture=self,
            run_id=run_id,
            metadata=metadata,
            samples=sensor_frames_from_mappings(samples),
            raw_capture=raw_capture,
        )


@dataclass(frozen=True, slots=True)
class GoldenReplayRun:
    fixture: GoldenReplayFixture
    run_id: str
    metadata: RunMetadata
    samples: list[SensorFrame]
    raw_capture: RawRunCapture


@dataclass(frozen=True, slots=True)
class GoldenReplayResult:
    fixture: GoldenReplayFixture
    analysis: dict[str, object]
    manifest: WholeRunArtifactManifest
    artifact_contents: Mapping[str, bytes]


@dataclass(frozen=True, slots=True)
class GoldenReplayBenchmarkResult:
    elapsed_s: float
    peak_memory_bytes: int
    result: GoldenReplayResult


class GoldenReplayRecorder:
    """Minimal async persistence port used by the executor harness."""

    def __init__(self) -> None:
        self.analysis: dict[str, object] | None = None
        self.manifest: WholeRunArtifactManifest | None = None
        self.artifact_contents: dict[str, bytes] = {}
        self.errors: list[tuple[str, str]] = []

    async def astore_whole_run_artifacts(
        self,
        run_id: str,
        manifest: WholeRunArtifactManifest,
        *,
        artifact_contents: Mapping[str, bytes],
    ) -> WholeRunArtifactManifest:
        self.manifest = manifest
        self.artifact_contents = dict(artifact_contents)
        return manifest

    async def astore_analysis(
        self,
        _run_id: str,
        analysis: PersistedAnalysis | Mapping[str, object],
    ) -> None:
        if isinstance(analysis, PersistedAnalysis):
            self.analysis = cast(dict[str, object], analysis.to_json_object())
        else:
            self.analysis = dict(analysis)

    async def astore_analysis_error(self, run_id: str, error: str) -> None:
        self.errors.append((run_id, error))


def golden_replay_fixtures(*, fast_ci_only: bool = False) -> tuple[GoldenReplayFixture, ...]:
    from test_support.golden_replay_catalog import golden_replay_fixture_catalog

    fixtures = golden_replay_fixture_catalog()
    if fast_ci_only:
        return tuple(fixture for fixture in fixtures if fixture.fast_ci)
    return fixtures


def execute_golden_replay_fixture(
    fixture: GoldenReplayFixture,
    *,
    duration_s: float | None = None,
    analysis_runner: object | None = None,
) -> GoldenReplayResult:
    run = fixture.build(duration_s=duration_s)
    recorder = GoldenReplayRecorder()
    result = execute_post_analysis(
        run_id=run.run_id,
        db=cast(RunPersistence, recorder),
        config=PostAnalysisExecutionConfig(
            load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
                run_id=run_id,
                metadata=run.metadata,
                language=run.metadata.language or "en",
                samples=list(run.samples),
                total_summary_row_count=len(run.samples),
                stride=1,
                summary_duration_s=duration_s or fixture.duration_s,
                context_samples=list(run.samples),
                raw_capture=run.raw_capture,
                raw_capture_manifest=run.raw_capture.manifest,
            ),
            analysis_runner=(
                build_post_analysis_summary
                if analysis_runner is None
                else cast(Any, analysis_runner)
            ),
        ),
    )
    assert isinstance(result, PostAnalysisExecutionSuccess)
    assert recorder.analysis is not None
    assert recorder.manifest is not None
    return GoldenReplayResult(
        fixture=fixture,
        analysis=recorder.analysis,
        manifest=recorder.manifest,
        artifact_contents=recorder.artifact_contents,
    )


def benchmark_golden_replay_fixture(
    fixture: GoldenReplayFixture,
    *,
    duration_s: float,
) -> GoldenReplayBenchmarkResult:
    tracemalloc.start()
    started = perf_counter()
    try:
        result = execute_golden_replay_fixture(
            fixture,
            duration_s=duration_s,
            analysis_runner=_minimal_benchmark_summary,
        )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return GoldenReplayBenchmarkResult(
        elapsed_s=perf_counter() - started,
        peak_memory_bytes=peak,
        result=result,
    )


def _minimal_benchmark_summary(run: PostAnalysisRunInput) -> PersistedAnalysis:
    return PersistedAnalysis.from_json_object(
        {
            "run_id": run.run_id,
            "findings": [],
            "top_causes": [],
            "warnings": [],
            "run_suitability": [],
            "analysis_metadata": {
                "analyzed_sample_count": len(run.samples),
                "benchmark_fixture": run.run_id,
            },
        }
    )


def write_golden_replay_snapshot(
    *,
    result: GoldenReplayResult,
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result.fixture.case_id}.json"
    top_causes = result.analysis.get("top_causes")
    analysis_metadata = result.analysis.get("analysis_metadata")
    diagnosis_summaries = result.analysis.get("whole_run_diagnosis_summaries")
    path.write_text(
        json.dumps(
            {
                "case_id": result.fixture.case_id,
                "title": result.fixture.title,
                "seed": result.fixture.seed,
                "expected": _expected_snapshot(result.fixture.expected),
                "top_causes": top_causes if isinstance(top_causes, list) else [],
                "whole_run_diagnosis_summaries": (
                    diagnosis_summaries if isinstance(diagnosis_summaries, list) else []
                ),
                "analysis_metadata": (
                    analysis_metadata if isinstance(analysis_metadata, dict) else {}
                ),
                "artifact_keys": [artifact.artifact_key for artifact in result.manifest.artifacts],
                "artifact_paths": result.manifest.generated_artifact_paths,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def _expected_snapshot(expected: GoldenReplayExpected) -> dict[str, object]:
    return {
        "suspected_source": expected.suspected_source,
        "strongest_location": expected.strongest_location,
        "confidence_range": list(expected.confidence_range),
        "confidence_label_key": expected.confidence_label_key,
        "unavailable_reasons": list(expected.unavailable_reasons),
        "tolerance_bands": dict(expected.tolerance_bands or {}),
        "max_false_positive_confidence": expected.max_false_positive_confidence,
        "required_warning_codes": list(expected.required_warning_codes),
        "required_metadata_minimums": dict(expected.required_metadata_minimums or {}),
    }


def _metadata_for_fixture(fixture: GoldenReplayFixture, *, run_id: str) -> RunMetadata:
    return run_metadata_from_mapping(
        standard_metadata(
            run_id=run_id,
            raw_sample_rate_hz=fixture.sample_rate_hz,
            sample_rate_hz=fixture.sample_rate_hz,
            feature_interval_s=1.0,
            fft_window_size_samples=fixture.fft_window_size_samples,
            accel_scale_g_per_lsb=_RAW_ACCEL_SCALE_G_PER_LSB,
            final_drive_ratio=fixture.final_drive_ratio,
            current_gear_ratio=fixture.current_gear_ratio,
        )
    )


def _summary_samples(
    fixture: GoldenReplayFixture,
    *,
    run_id: str,
    duration_s: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    summary_count = max(1, int(duration_s))
    for index in range(summary_count):
        for sensor in ALL_SENSORS:
            rows.append(
                _summary_sample(
                    fixture,
                    run_id=run_id,
                    t_s=float(index),
                    sensor=sensor,
                    transient_active=_transient_active(fixture, t_s=float(index)),
                )
            )
    return rows


def _summary_sample(
    fixture: GoldenReplayFixture,
    *,
    run_id: str,
    t_s: float,
    sensor: str,
    transient_active: bool,
) -> dict[str, Any]:
    frequency = _effective_frequency(fixture, transient_active=transient_active)
    amp = _sensor_amp(fixture, sensor=sensor, transient_active=transient_active)
    speed = _speed_kmh_at_t(fixture, t_s=t_s)
    peaks = _peaks_for_frequency(frequency, amp)
    row = make_sample(
        t_s=t_s,
        speed_kmh=speed,
        client_name=sensor,
        client_id=sensor,
        location=sensor,
        top_peaks=peaks,
        vibration_strength_db=28.0 if amp >= fixture.signal_amp_g else 12.0,
        strength_floor_amp_g=0.004,
        engine_rpm=fixture.engine_rpm,
        strength_peak_amp_g=max((peak["amp"] for peak in peaks), default=0.004),
    )
    row["run_id"] = run_id
    row["speed_source"] = fixture.speed_source
    if fixture.speed_kmh is None and fixture.speed_sweep_kmh is None:
        row.pop("speed_kmh", None)
    if fixture.engine_rpm is not None:
        row["engine_rpm_source"] = "obd2"
    return row


def _raw_capture_for_fixture(
    fixture: GoldenReplayFixture,
    *,
    run_id: str,
    duration_s: float,
) -> RawRunCapture:
    sensors = tuple(
        _raw_sensor_data(
            fixture,
            run_id=run_id,
            sensor=sensor,
            duration_s=duration_s,
        )
        for sensor in ALL_SENSORS
    )
    manifest = RawCaptureManifest(
        run_id=run_id,
        relative_dir=f"raw-runs/{run_id}",
        sensors=tuple(sensor.manifest for sensor in sensors),
        total_samples=sum(sensor.manifest.sample_count for sensor in sensors),
        total_bytes=sum(sensor.manifest.bytes_written for sensor in sensors),
        created_at="2026-01-01T00:00:00Z",
        run_start_monotonic_us=_RUN_START_US,
    )
    return RawRunCapture(manifest=manifest, sensors=sensors)


def _raw_sensor_data(
    fixture: GoldenReplayFixture,
    *,
    run_id: str,
    sensor: str,
    duration_s: float,
) -> RawCaptureSensorData:
    total_samples = max(fixture.fft_window_size_samples, int(duration_s * fixture.sample_rate_hz))
    samples = _sensor_waveform(fixture, sensor=sensor, total_samples=total_samples)
    chunk = RawCaptureChunkIndex(
        sample_start=0,
        sample_count=total_samples,
        t0_us=_RUN_START_US,
        byte_offset=0,
    )
    manifest = RawCaptureSensorManifest(
        client_id=sensor,
        sample_rate_hz=fixture.sample_rate_hz,
        data_file=f"{sensor}.raw.i16le",
        index_file=f"{sensor}.index.jsonl",
        sample_count=total_samples,
        chunk_count=1,
        bytes_written=int(samples.shape[0] * samples.shape[1] * 2),
        first_t0_us=_RUN_START_US,
        last_t0_us=_RUN_START_US,
        clock_sync=RawCaptureSensorClockSync(
            clock_domain="server_monotonic",
            proof_state="verified",
            observed_monotonic_us=_RUN_START_US + 10_000,
            last_sync_monotonic_us=_RUN_START_US,
            sync_offset_us=0,
            sync_rtt_us=2_000,
            max_sync_age_us=15_000_000,
            max_sync_rtt_us=50_000,
        ),
        declared_sample_rate_hz=fixture.sample_rate_hz,
        sample_rate_proof_state="observed_consistent",
    )
    return RawCaptureSensorData(manifest=manifest, samples_i16=samples, chunks=(chunk,))


def _sensor_waveform(
    fixture: GoldenReplayFixture,
    *,
    sensor: str,
    total_samples: int,
) -> np.ndarray:
    rng = np.random.default_rng(fixture.seed + sum(ord(char) for char in sensor))
    t = np.arange(total_samples, dtype=np.float64) / float(fixture.sample_rate_hz)
    frequency = _effective_frequency(fixture, transient_active=True)
    amp_g = _sensor_amp(fixture, sensor=sensor, transient_active=True)
    if frequency is None:
        base = np.zeros(total_samples, dtype=np.float64)
    else:
        envelope = np.ones(total_samples, dtype=np.float64)
        if fixture.transient_duration_s > 0.0:
            envelope[:] = 0.05
            transient_sample_count = min(
                total_samples,
                int(fixture.sample_rate_hz * fixture.transient_duration_s),
            )
            envelope[:transient_sample_count] = 1.0
        base = amp_g * envelope * np.sin((2.0 * pi * frequency * t) + _phase_for_sensor(sensor))
        if frequency * 2.0 < fixture.sample_rate_hz / 2.0:
            base += (amp_g * 0.35) * envelope * np.sin(2.0 * pi * frequency * 2.0 * t)
    for noise_freq in _NOISE_FREQS_HZ:
        if noise_freq < fixture.sample_rate_hz / 2.0:
            base += 0.004 * np.sin((2.0 * pi * noise_freq * t) + _phase_for_sensor(sensor))
    base += rng.normal(loc=0.0, scale=0.0015, size=total_samples)
    x = np.round(base / _RAW_ACCEL_SCALE_G_PER_LSB).astype(np.int16)
    y = np.round(base * 0.35 / _RAW_ACCEL_SCALE_G_PER_LSB).astype(np.int16)
    z = np.round(base * 0.15 / _RAW_ACCEL_SCALE_G_PER_LSB).astype(np.int16)
    return np.stack([x, y, z], axis=1)


def _phase_for_sensor(sensor: str) -> float:
    return (sum(ord(char) for char in sensor) % 17) * 0.11


def _transient_active(fixture: GoldenReplayFixture, *, t_s: float) -> bool:
    return fixture.transient_duration_s > 0.0 and t_s < fixture.transient_duration_s


def _effective_frequency(
    fixture: GoldenReplayFixture,
    *,
    transient_active: bool,
) -> float | None:
    if transient_active and fixture.transient_frequency_hz is not None:
        return fixture.transient_frequency_hz
    return fixture.primary_frequency_hz


def _speed_kmh_at_t(fixture: GoldenReplayFixture, *, t_s: float) -> float:
    if fixture.speed_sweep_kmh is not None:
        start, end = fixture.speed_sweep_kmh
        ratio = min(1.0, max(0.0, t_s / max(1.0, fixture.duration_s - 1.0)))
        return start + (end - start) * ratio
    return 0.0 if fixture.speed_kmh is None else fixture.speed_kmh


def _sensor_amp(
    fixture: GoldenReplayFixture,
    *,
    sensor: str,
    transient_active: bool,
) -> float:
    if fixture.primary_frequency_hz is None and fixture.transient_duration_s <= 0.0:
        return 0.006 if fixture.case_id == "noisy-sensor" else 0.003
    if fixture.transient_duration_s > 0.0 and not transient_active:
        return 0.004
    if fixture.strongest_sensor is None:
        return fixture.transfer_amp_g
    return fixture.signal_amp_g if sensor == fixture.strongest_sensor else fixture.transfer_amp_g


def _peaks_for_frequency(frequency: float | None, amp: float) -> list[dict[str, float]]:
    if frequency is None:
        return [
            {"hz": 37.0, "amp": amp},
            {"hz": 55.0, "amp": amp * 0.7},
        ]
    peaks = [{"hz": frequency, "amp": amp}]
    if frequency * 2.0 < 120.0:
        peaks.append({"hz": frequency * 2.0, "amp": amp * 0.35})
    peaks.append({"hz": 55.0, "amp": max(0.003, amp * 0.12)})
    return peaks
