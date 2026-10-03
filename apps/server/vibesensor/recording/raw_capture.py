"""Typed raw-capture artifact contracts shared by recording and history flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import numpy.typing as npt
from pydantic import model_validator

from vibesensor.common.json_contract import JsonContract

__all__ = [
    "RawCaptureChunk",
    "RawCaptureChunkIndex",
    "RawCaptureClockDomain",
    "RawCaptureLossStats",
    "RawCaptureManifest",
    "RawCaptureSampleRateProofState",
    "RawCaptureSensorClockSync",
    "RawCaptureSensorLossStats",
    "RawCaptureSensorData",
    "RawCaptureSensorManifest",
    "RawRunCapture",
]

type Int16Array = npt.NDArray[np.int16]
type RawCaptureClockDomain = Literal["server_monotonic", "unverified"]
type RawCaptureSampleRateProofState = Literal[
    "declared_only",
    "observed_consistent",
    "missing",
]
type RawCaptureClockProofState = Literal[
    "verified",
    "missing_sync",
    "stale_sync",
    "high_rtt",
    "missing_registry_record",
]

_RAW_CAPTURE_SCHEMA_VERSION = 7
_RAW_CAPTURE_STORAGE_TYPE = "run-directory-v1"
_RAW_CAPTURE_MODE = "full_run"


@dataclass(frozen=True, slots=True)
class RawCaptureChunk:
    """One raw waveform chunk queued from UDP ingest into the raw-capture store."""

    client_id: str
    sample_rate_hz: int
    t0_us: int
    sample_count: int
    samples_i16le: bytes


@dataclass(frozen=True, slots=True)
class RawCaptureChunkIndex(JsonContract):
    """Persistent index row locating one raw chunk inside a sensor stream file."""

    sample_start: int
    sample_count: int
    t0_us: int
    byte_offset: int


@dataclass(frozen=True, slots=True)
class RawCaptureLossStats(JsonContract):
    """Structured counts for raw chunk issues persisted alongside the run."""

    udp_ingest_queue_drop_count: int = 0
    late_packet_chunk_count: int = 0
    queue_overflow_chunk_count: int = 0
    invalid_chunk_count: int = 0
    write_error_chunk_count: int = 0

    @property
    def total_dropped_chunk_count(self) -> int:
        return (
            max(0, self.udp_ingest_queue_drop_count)
            + max(0, self.queue_overflow_chunk_count)
            + max(0, self.invalid_chunk_count)
            + max(0, self.write_error_chunk_count)
        )

    @property
    def total_loss_event_count(self) -> int:
        return self.total_dropped_chunk_count + max(0, self.late_packet_chunk_count)

    def merged(self, other: RawCaptureLossStats) -> RawCaptureLossStats:
        return RawCaptureLossStats(
            udp_ingest_queue_drop_count=(
                self.udp_ingest_queue_drop_count + other.udp_ingest_queue_drop_count
            ),
            late_packet_chunk_count=self.late_packet_chunk_count + other.late_packet_chunk_count,
            queue_overflow_chunk_count=(
                self.queue_overflow_chunk_count + other.queue_overflow_chunk_count
            ),
            invalid_chunk_count=self.invalid_chunk_count + other.invalid_chunk_count,
            write_error_chunk_count=(self.write_error_chunk_count + other.write_error_chunk_count),
        )


@dataclass(frozen=True, slots=True)
class RawCaptureSensorLossStats(JsonContract):
    """Per-sensor raw chunk loss counts persisted alongside the manifest."""

    client_id: str
    losses: RawCaptureLossStats = field(default_factory=RawCaptureLossStats)

    @property
    def total_dropped_chunk_count(self) -> int:
        return self.losses.total_dropped_chunk_count

    @property
    def total_loss_event_count(self) -> int:
        return self.losses.total_loss_event_count

    @property
    def late_packet_chunk_count(self) -> int:
        return max(0, self.losses.late_packet_chunk_count)


@dataclass(frozen=True, slots=True)
class RawCaptureSensorClockSync(JsonContract):
    """Persisted proof about whether one sensor's ``t0_us`` uses server monotonic time."""

    clock_domain: RawCaptureClockDomain = "unverified"
    proof_state: RawCaptureClockProofState = "missing_sync"
    observed_monotonic_us: int | None = None
    last_sync_monotonic_us: int | None = None
    sync_offset_us: int | None = None
    sync_rtt_us: int | None = None
    max_sync_age_us: int | None = None
    max_sync_rtt_us: int | None = None

    @property
    def verified(self) -> bool:
        return self.clock_domain == "server_monotonic" and self.proof_state == "verified"


@dataclass(frozen=True, slots=True)
class RawCaptureSensorManifest(JsonContract):
    """One sensor stream persisted inside a raw run-artifact bundle."""

    client_id: str
    sample_rate_hz: int
    data_file: str
    index_file: str
    sample_count: int
    chunk_count: int
    bytes_written: int
    first_t0_us: int | None = None
    last_t0_us: int | None = None
    clock_sync: RawCaptureSensorClockSync | None = None
    declared_sample_rate_hz: int | None = None
    sample_rate_proof_state: RawCaptureSampleRateProofState = "declared_only"

    @property
    def sample_rate_unverified(self) -> bool:
        return self.sample_rate_proof_state != "observed_consistent"

    @property
    def sample_rate_corrected(self) -> bool:
        declared = self.declared_sample_rate_hz
        return (
            declared is not None
            and declared > 0
            and self.sample_rate_hz > 0
            and self.sample_rate_hz != declared
        )

    @model_validator(mode="before")
    @classmethod
    def _default_declared_sample_rate(cls, data: object) -> object:
        # Manifests before schema v6 carry no declared rate; the stored rate was it.
        if isinstance(data, dict) and not data.get("declared_sample_rate_hz"):
            return {**data, "declared_sample_rate_hz": data.get("sample_rate_hz") or None}
        return data


@dataclass(frozen=True, slots=True)
class RawCaptureManifest(JsonContract):
    """Compact manifest persisted on a run record for one raw artifact bundle."""

    run_id: str
    relative_dir: str
    sensors: tuple[RawCaptureSensorManifest, ...]
    total_samples: int
    total_bytes: int
    created_at: str
    run_start_monotonic_us: int | None = None
    sensor_losses: tuple[RawCaptureSensorLossStats, ...] = ()
    losses: RawCaptureLossStats = field(default_factory=RawCaptureLossStats)
    schema_version: int = _RAW_CAPTURE_SCHEMA_VERSION
    storage_type: str = _RAW_CAPTURE_STORAGE_TYPE
    capture_mode: str = _RAW_CAPTURE_MODE

    def sensor_manifest(self, client_id: str) -> RawCaptureSensorManifest | None:
        for sensor in self.sensors:
            if sensor.client_id == client_id:
                return sensor
        return None

    def sensor_loss(self, client_id: str) -> RawCaptureSensorLossStats | None:
        for sensor_loss in self.sensor_losses:
            if sensor_loss.client_id == client_id:
                return sensor_loss
        return None

    @property
    def total_chunk_count(self) -> int:
        return sum(max(0, sensor.chunk_count) for sensor in self.sensors)

    @property
    def total_dropped_chunk_count(self) -> int:
        sensor_total = sum(
            max(0, sensor_loss.total_dropped_chunk_count) for sensor_loss in self.sensor_losses
        )
        return self.losses.total_dropped_chunk_count or sensor_total

    @property
    def total_late_packet_chunk_count(self) -> int:
        sensor_total = sum(
            max(0, sensor_loss.late_packet_chunk_count) for sensor_loss in self.sensor_losses
        )
        return max(0, self.losses.late_packet_chunk_count) or sensor_total

    @property
    def total_loss_event_count(self) -> int:
        sensor_total = sum(
            max(0, sensor_loss.total_loss_event_count) for sensor_loss in self.sensor_losses
        )
        return self.losses.total_loss_event_count or sensor_total


@dataclass(frozen=True, slots=True)
class RawCaptureSensorData:
    """Decoded raw waveform stream plus its persisted chunk index."""

    manifest: RawCaptureSensorManifest
    samples_i16: Int16Array
    chunks: tuple[RawCaptureChunkIndex, ...]


@dataclass(frozen=True, slots=True)
class RawRunCapture:
    """Fully loaded raw capture bundle for one run."""

    manifest: RawCaptureManifest
    sensors: tuple[RawCaptureSensorData, ...]

    def sensor_data(self, client_id: str) -> RawCaptureSensorData | None:
        for sensor in self.sensors:
            if sensor.manifest.client_id == client_id:
                return sensor
        return None
