from __future__ import annotations

from dataclasses import replace

from vibesensor.shared.raw_capture_quality import assess_raw_capture_loss_policy
from vibesensor.shared.types.raw_capture import (
    RawCaptureLossStats,
    RawCaptureManifest,
    RawCaptureSensorLossStats,
    RawCaptureSensorManifest,
)


def _manifest(*, queue_overflow: int, chunk_count: int = 1000) -> RawCaptureManifest:
    sensor = RawCaptureSensorManifest(
        client_id="sensor-a",
        sample_rate_hz=800,
        data_file="sensor-a.raw.i16le",
        index_file="sensor-a.index.jsonl",
        sample_count=chunk_count * 64,
        chunk_count=chunk_count,
        bytes_written=chunk_count * 64 * 3 * 2,
    )
    losses = RawCaptureLossStats(queue_overflow_chunk_count=queue_overflow)
    return RawCaptureManifest(
        run_id="run-quality",
        relative_dir="raw-runs/run-quality",
        sensors=(sensor,),
        total_samples=sensor.sample_count,
        total_bytes=sensor.bytes_written,
        created_at="2026-01-01T00:00:00Z",
        sensor_losses=(RawCaptureSensorLossStats(client_id="sensor-a", losses=losses),),
        losses=losses,
    )


def test_raw_capture_loss_policy_warns_for_first_queue_overflow() -> None:
    assessment = assess_raw_capture_loss_policy(_manifest(queue_overflow=1))

    assert assessment.severity == "warn"
    assert assessment.reason == "raw_capture_loss_warn"
    assert assessment.gate_whole_run is False


def test_raw_capture_loss_policy_reports_ok_when_no_manifest_is_available() -> None:
    assessment = assess_raw_capture_loss_policy(None)

    assert assessment.severity == "ok"
    assert assessment.reason == "raw_capture_not_available"
    assert assessment.gate_whole_run is False
    assert assessment.total_loss_event_count == 0


def test_raw_capture_loss_policy_gates_whole_run_for_fatal_queue_overflow() -> None:
    assessment = assess_raw_capture_loss_policy(_manifest(queue_overflow=120))

    assert assessment.severity == "fatal"
    assert assessment.reason == "raw_capture_queue_overflow_fatal"
    assert assessment.gate_whole_run is True
    assert assessment.queue_overflow_chunk_count == 120


def test_raw_capture_loss_policy_degrades_for_sensor_drop_ratio() -> None:
    manifest = replace(_manifest(queue_overflow=0, chunk_count=100), losses=RawCaptureLossStats())
    losses = RawCaptureLossStats(invalid_chunk_count=2)
    manifest = replace(
        manifest,
        sensor_losses=(RawCaptureSensorLossStats(client_id="sensor-a", losses=losses),),
        losses=losses,
    )

    assessment = assess_raw_capture_loss_policy(manifest)

    assert assessment.severity == "degraded"
    assert assessment.max_sensor_drop_ratio > 0.01
