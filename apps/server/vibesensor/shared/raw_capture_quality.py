"""Raw-capture loss policy used by history, reports, and post-analysis gating."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.raw_capture import (
    RawCaptureManifest,
    RawCaptureSensorLossStats,
)

type RawCaptureLossPolicySeverity = Literal["ok", "warn", "degraded", "fatal"]

_DEGRADED_SENSOR_DROP_RATIO = 0.01
_FATAL_SENSOR_DROP_RATIO = 0.05
_DEGRADED_LOSS_EVENTS_PER_MINUTE = 3.0
_FATAL_LOSS_EVENTS_PER_MINUTE = 30.0
_DEGRADED_QUEUE_OVERFLOW_CHUNKS = 10
_FATAL_QUEUE_OVERFLOW_CHUNKS = 100
_MIN_LOSS_RATE_DURATION_S = 60.0


@dataclass(frozen=True, slots=True)
class RawCaptureLossPolicyAssessment:
    """Compact policy result for persisted raw-capture loss counters."""

    severity: RawCaptureLossPolicySeverity
    reason: str
    gate_whole_run: bool
    affected_sensor_count: int
    queue_overflow_sensor_count: int
    total_chunk_count: int
    total_loss_event_count: int
    total_dropped_chunk_count: int
    queue_overflow_chunk_count: int
    max_sensor_drop_ratio: float
    max_sensor_loss_events_per_minute: float

    def to_json_object(self) -> JsonObject:
        return {
            "severity": self.severity,
            "reason": self.reason,
            "gate_whole_run": self.gate_whole_run,
            "affected_sensor_count": self.affected_sensor_count,
            "queue_overflow_sensor_count": self.queue_overflow_sensor_count,
            "total_chunk_count": self.total_chunk_count,
            "total_loss_event_count": self.total_loss_event_count,
            "total_dropped_chunk_count": self.total_dropped_chunk_count,
            "queue_overflow_chunk_count": self.queue_overflow_chunk_count,
            "max_sensor_drop_ratio": round(self.max_sensor_drop_ratio, 6),
            "max_sensor_loss_events_per_minute": round(
                self.max_sensor_loss_events_per_minute,
                3,
            ),
        }


def assess_raw_capture_loss_policy(
    manifest: RawCaptureManifest | None,
) -> RawCaptureLossPolicyAssessment:
    """Classify raw-capture loss against stable per-sensor/run-duration thresholds."""
    if manifest is None:
        return RawCaptureLossPolicyAssessment(
            severity="ok",
            reason="raw_capture_not_available",
            gate_whole_run=False,
            affected_sensor_count=0,
            queue_overflow_sensor_count=0,
            total_chunk_count=0,
            total_loss_event_count=0,
            total_dropped_chunk_count=0,
            queue_overflow_chunk_count=0,
            max_sensor_drop_ratio=0.0,
            max_sensor_loss_events_per_minute=0.0,
        )
    sensor_durations = {
        sensor.client_id: _sensor_duration_s(
            sample_count=sensor.sample_count,
            sample_rate_hz=sensor.sample_rate_hz,
            first_t0_us=sensor.first_t0_us,
            last_t0_us=sensor.last_t0_us,
        )
        for sensor in manifest.sensors
    }
    sensor_chunk_counts = {
        sensor.client_id: max(0, int(sensor.chunk_count)) for sensor in manifest.sensors
    }
    affected_sensor_count = 0
    queue_overflow_sensor_count = 0
    max_sensor_drop_ratio = 0.0
    max_sensor_loss_events_per_minute = 0.0
    for sensor_loss in manifest.sensor_losses:
        if sensor_loss.total_loss_event_count <= 0:
            continue
        affected_sensor_count += 1
        if sensor_loss.losses.queue_overflow_chunk_count > 0:
            queue_overflow_sensor_count += 1
        max_sensor_drop_ratio = max(
            max_sensor_drop_ratio,
            _sensor_drop_ratio(sensor_loss, sensor_chunk_counts.get(sensor_loss.client_id, 0)),
        )
        max_sensor_loss_events_per_minute = max(
            max_sensor_loss_events_per_minute,
            _loss_events_per_minute(
                sensor_loss.total_loss_event_count,
                sensor_durations.get(sensor_loss.client_id),
            ),
        )
    total_chunk_count = manifest.total_chunk_count
    total_loss_event_count = manifest.total_loss_event_count
    total_dropped_chunk_count = manifest.total_dropped_chunk_count
    queue_overflow_chunk_count = manifest.losses.queue_overflow_chunk_count
    severity, reason = _classify_loss(
        total_loss_event_count=total_loss_event_count,
        queue_overflow_chunk_count=queue_overflow_chunk_count,
        write_error_chunk_count=manifest.losses.write_error_chunk_count,
        max_sensor_drop_ratio=max_sensor_drop_ratio,
        max_sensor_loss_events_per_minute=max_sensor_loss_events_per_minute,
    )
    return RawCaptureLossPolicyAssessment(
        severity=severity,
        reason=reason,
        gate_whole_run=severity == "fatal",
        affected_sensor_count=affected_sensor_count,
        queue_overflow_sensor_count=queue_overflow_sensor_count,
        total_chunk_count=total_chunk_count,
        total_loss_event_count=total_loss_event_count,
        total_dropped_chunk_count=total_dropped_chunk_count,
        queue_overflow_chunk_count=queue_overflow_chunk_count,
        max_sensor_drop_ratio=max_sensor_drop_ratio,
        max_sensor_loss_events_per_minute=max_sensor_loss_events_per_minute,
    )


def _classify_loss(
    *,
    total_loss_event_count: int,
    queue_overflow_chunk_count: int,
    write_error_chunk_count: int,
    max_sensor_drop_ratio: float,
    max_sensor_loss_events_per_minute: float,
) -> tuple[RawCaptureLossPolicySeverity, str]:
    if total_loss_event_count <= 0:
        return "ok", "raw_capture_loss_ok"
    if (
        max_sensor_drop_ratio >= _FATAL_SENSOR_DROP_RATIO
        or max_sensor_loss_events_per_minute >= _FATAL_LOSS_EVENTS_PER_MINUTE
        or queue_overflow_chunk_count >= _FATAL_QUEUE_OVERFLOW_CHUNKS
    ):
        return "fatal", "raw_capture_queue_overflow_fatal"
    if (
        max_sensor_drop_ratio >= _DEGRADED_SENSOR_DROP_RATIO
        or max_sensor_loss_events_per_minute >= _DEGRADED_LOSS_EVENTS_PER_MINUTE
        or queue_overflow_chunk_count >= _DEGRADED_QUEUE_OVERFLOW_CHUNKS
        or write_error_chunk_count > 0
    ):
        return "degraded", "raw_capture_loss_degraded"
    return "warn", "raw_capture_loss_warn"


def _sensor_drop_ratio(sensor_loss: RawCaptureSensorLossStats, chunk_count: int) -> float:
    dropped = max(0, int(sensor_loss.total_dropped_chunk_count))
    denominator = max(0, int(chunk_count)) + dropped
    if denominator <= 0:
        return 0.0
    return dropped / float(denominator)


def _loss_events_per_minute(loss_event_count: int, duration_s: float | None) -> float:
    if duration_s is None or duration_s < _MIN_LOSS_RATE_DURATION_S:
        return 0.0
    return max(0, int(loss_event_count)) / (duration_s / 60.0)


def _sensor_duration_s(
    *,
    sample_count: int,
    sample_rate_hz: int,
    first_t0_us: int | None,
    last_t0_us: int | None,
) -> float | None:
    if sample_count > 0 and sample_rate_hz > 0:
        return max(0.0, float(sample_count) / float(sample_rate_hz))
    if first_t0_us is not None and last_t0_us is not None and last_t0_us >= first_t0_us:
        return max(0.0, (last_t0_us - first_t0_us) / 1_000_000.0)
    return None
