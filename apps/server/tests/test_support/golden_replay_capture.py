"""Golden replay run materialization helpers."""

from __future__ import annotations

from math import pi
from typing import Any

import numpy as np

from test_support.core import ALL_SENSORS, standard_metadata
from test_support.golden_replay_types import GoldenReplayFixture, GoldenReplayRun
from test_support.sample_scenarios import make_sample
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.types.raw_capture import (
    RawCaptureChunkIndex,
    RawCaptureManifest,
    RawCaptureSensorClockSync,
    RawCaptureSensorData,
    RawCaptureSensorManifest,
    RawRunCapture,
)
from vibesensor.shared.types.run_schema import RunMetadata

_RUN_START_US = 1_000_000
_RAW_ACCEL_SCALE_G_PER_LSB = 0.001
_NOISE_FREQS_HZ = (37.0, 55.0)


def build_golden_replay_run(
    fixture: GoldenReplayFixture,
    *,
    duration_s: float | None = None,
) -> GoldenReplayRun:
    run_id = f"golden-{fixture.case_id}"
    actual_duration_s = fixture.duration_s if duration_s is None else duration_s
    metadata = _metadata_for_fixture(fixture, run_id=run_id)
    samples = _summary_samples(fixture, run_id=run_id, duration_s=actual_duration_s)
    raw_capture = _raw_capture_for_fixture(
        fixture,
        run_id=run_id,
        duration_s=actual_duration_s,
    )
    return GoldenReplayRun(
        fixture=fixture,
        run_id=run_id,
        metadata=metadata,
        samples=sensor_frames_from_mappings(samples),
        raw_capture=raw_capture,
    )


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
