"""Exercise processing payload builders for intake stats and alignment."""

from __future__ import annotations

from typing import cast

from vibesensor.infra.processing.buffers import ClientBuffer
from vibesensor.infra.processing.models import ProcessorConfig
from vibesensor.infra.processing.payload import (
    build_intake_stats_payload,
    build_time_alignment_payload,
)
from vibesensor.shared.types.payload_types import IntakeStatsPayload, WorkerPoolStats


def _config(fft_n: int = 256) -> ProcessorConfig:
    return ProcessorConfig(
        sample_rate_hz=200,
        waveform_seconds=2,
        waveform_display_hz=50,
        fft_n=fft_n,
        spectrum_min_hz=0.0,
        spectrum_max_hz=100.0,
        accel_scale_g_per_lsb=None,
    )


def test_build_intake_stats_payload_adds_worker_pool_stats() -> None:
    base_stats: IntakeStatsPayload = {
        "total_ingested_samples": 10,
        "total_compute_calls": 2,
        "last_compute_duration_s": 0.1,
        "last_compute_all_duration_s": 0.2,
        "last_ingest_duration_s": 0.05,
    }
    worker_pool_stats: WorkerPoolStats = {
        "max_workers": 2,
        "max_queue_size": 2,
        "max_pending_tasks": 4,
        "total_tasks": 7,
        "pending_tasks": 1,
        "queued_tasks": 0,
        "running_tasks": 1,
        "rejected_tasks": 0,
        "total_run_s": 1.5,
        "avg_run_s": 0.75,
        "total_submit_wait_s": 0.2,
        "avg_submit_wait_s": 0.1,
        "default_submit_timeout_s": None,
        "alive": True,
    }

    payload = build_intake_stats_payload(base_stats, worker_pool_stats)

    assert payload["total_ingested_samples"] == 10
    assert payload["worker_pool"] == worker_pool_stats
    assert "worker_pool" not in base_stats


def test_build_time_alignment_payload_handles_overlap_and_exclusions() -> None:
    buf1 = cast(ClientBuffer, object())
    buf2 = cast(ClientBuffer, object())
    buffers = {"s1": buf1, "s2": buf2}

    def _analysis_time_range(buf: ClientBuffer) -> tuple[float, float, bool] | None:
        if buf is buf1:
            return (10.0, 12.0, True)
        if buf is buf2:
            return (11.0, 13.0, False)
        return None

    payload = build_time_alignment_payload(
        buffers,
        ["s1", "missing", "s2"],
        analysis_time_range_fn=_analysis_time_range,
    )

    assert payload["sensors_included"] == ["s1", "s2"]
    assert payload["sensors_excluded"] == ["missing"]
    assert payload["aligned"] is False
    assert payload["clock_synced"] is False
    assert payload["shared_window"] is not None
    assert payload["shared_window"]["duration_s"] == 1.0
    assert payload["overlap_ratio"] == 0.3333


def test_build_time_alignment_payload_single_sensor_is_trivially_aligned() -> None:
    buf = cast(ClientBuffer, object())

    payload = build_time_alignment_payload(
        {"s1": buf},
        ["s1"],
        analysis_time_range_fn=lambda _: (5.0, 7.0, True),
    )

    assert payload["aligned"] is True
    assert payload["clock_synced"] is True
    assert payload["shared_window"] is None
    assert payload["overlap_ratio"] == 1.0
