"""Typed raw-capture artifact contracts shared by recording and history flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import numpy.typing as npt

from vibesensor.shared.types.json_types import JsonObject, JsonValue, is_json_object

__all__ = [
    "RawCaptureChunk",
    "RawCaptureChunkIndex",
    "RawCaptureClockDomain",
    "RawCaptureLossStats",
    "RawCaptureManifest",
    "RawCaptureSensorClockSync",
    "RawCaptureSensorLossStats",
    "RawCaptureSensorData",
    "RawCaptureSensorManifest",
    "RawCaptureSensorRange",
    "RawRunCapture",
]

type Int16Array = npt.NDArray[np.int16]
type RawCaptureCoverageState = Literal["missing", "empty", "partial", "full"]
type RawCaptureClockDomain = Literal["server_monotonic", "unverified"]
type RawCaptureClockProofState = Literal[
    "verified",
    "missing_sync",
    "stale_sync",
    "high_rtt",
    "missing_registry_record",
]

_RAW_CAPTURE_SCHEMA_VERSION = 4
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
class RawCaptureChunkIndex:
    """Persistent index row locating one raw chunk inside a sensor stream file."""

    sample_start: int
    sample_count: int
    t0_us: int
    byte_offset: int

    def to_json_object(self) -> JsonObject:
        return {
            "sample_start": self.sample_start,
            "sample_count": self.sample_count,
            "t0_us": self.t0_us,
            "byte_offset": self.byte_offset,
        }

    @classmethod
    def from_mapping(cls, data: JsonObject) -> RawCaptureChunkIndex:
        return cls(
            sample_start=_int_from_json(data.get("sample_start")),
            sample_count=_int_from_json(data.get("sample_count")),
            t0_us=_int_from_json(data.get("t0_us")),
            byte_offset=_int_from_json(data.get("byte_offset")),
        )


@dataclass(frozen=True, slots=True)
class RawCaptureLossStats:
    """Structured counts for raw chunks lost before persistence."""

    queue_overflow_chunk_count: int = 0
    invalid_chunk_count: int = 0
    write_error_chunk_count: int = 0

    @property
    def total_dropped_chunk_count(self) -> int:
        return (
            max(0, self.queue_overflow_chunk_count)
            + max(0, self.invalid_chunk_count)
            + max(0, self.write_error_chunk_count)
        )

    def to_json_object(self) -> JsonObject:
        return {
            "queue_overflow_chunk_count": self.queue_overflow_chunk_count,
            "invalid_chunk_count": self.invalid_chunk_count,
            "write_error_chunk_count": self.write_error_chunk_count,
        }

    @classmethod
    def from_mapping(cls, data: JsonObject) -> RawCaptureLossStats:
        return cls(
            queue_overflow_chunk_count=_int_from_json(data.get("queue_overflow_chunk_count")),
            invalid_chunk_count=_int_from_json(data.get("invalid_chunk_count")),
            write_error_chunk_count=_int_from_json(data.get("write_error_chunk_count")),
        )

    def merged(self, other: RawCaptureLossStats) -> RawCaptureLossStats:
        return RawCaptureLossStats(
            queue_overflow_chunk_count=(
                self.queue_overflow_chunk_count + other.queue_overflow_chunk_count
            ),
            invalid_chunk_count=self.invalid_chunk_count + other.invalid_chunk_count,
            write_error_chunk_count=(self.write_error_chunk_count + other.write_error_chunk_count),
        )


@dataclass(frozen=True, slots=True)
class RawCaptureSensorLossStats:
    """Per-sensor raw chunk loss counts persisted alongside the manifest."""

    client_id: str
    losses: RawCaptureLossStats = field(default_factory=RawCaptureLossStats)

    @property
    def total_dropped_chunk_count(self) -> int:
        return self.losses.total_dropped_chunk_count

    def to_json_object(self) -> JsonObject:
        return {
            "client_id": self.client_id,
            "losses": self.losses.to_json_object(),
        }

    @classmethod
    def from_mapping(cls, data: JsonObject) -> RawCaptureSensorLossStats:
        losses_raw = data.get("losses")
        losses = (
            RawCaptureLossStats.from_mapping(losses_raw)
            if is_json_object(losses_raw)
            else RawCaptureLossStats()
        )
        return cls(
            client_id=_str_from_json(data.get("client_id")),
            losses=losses,
        )


@dataclass(frozen=True, slots=True)
class RawCaptureSensorClockSync:
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

    @property
    def sync_age_us(self) -> int | None:
        if self.observed_monotonic_us is None or self.last_sync_monotonic_us is None:
            return None
        return max(0, self.observed_monotonic_us - self.last_sync_monotonic_us)

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "clock_domain": self.clock_domain,
            "proof_state": self.proof_state,
        }
        if self.observed_monotonic_us is not None:
            payload["observed_monotonic_us"] = self.observed_monotonic_us
        if self.last_sync_monotonic_us is not None:
            payload["last_sync_monotonic_us"] = self.last_sync_monotonic_us
        if self.sync_offset_us is not None:
            payload["sync_offset_us"] = self.sync_offset_us
        if self.sync_rtt_us is not None:
            payload["sync_rtt_us"] = self.sync_rtt_us
        if self.max_sync_age_us is not None:
            payload["max_sync_age_us"] = self.max_sync_age_us
        if self.max_sync_rtt_us is not None:
            payload["max_sync_rtt_us"] = self.max_sync_rtt_us
        return payload

    @classmethod
    def from_mapping(cls, data: JsonObject) -> RawCaptureSensorClockSync:
        return cls(
            clock_domain=_str_from_json(data.get("clock_domain"), "unverified"),  # type: ignore[arg-type]
            proof_state=_str_from_json(data.get("proof_state"), "missing_sync"),  # type: ignore[arg-type]
            observed_monotonic_us=_int_or_none(data.get("observed_monotonic_us")),
            last_sync_monotonic_us=_int_or_none(data.get("last_sync_monotonic_us")),
            sync_offset_us=_int_or_none(data.get("sync_offset_us")),
            sync_rtt_us=_int_or_none(data.get("sync_rtt_us")),
            max_sync_age_us=_int_or_none(data.get("max_sync_age_us")),
            max_sync_rtt_us=_int_or_none(data.get("max_sync_rtt_us")),
        )


@dataclass(frozen=True, slots=True)
class RawCaptureSensorManifest:
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

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "client_id": self.client_id,
            "sample_rate_hz": self.sample_rate_hz,
            "data_file": self.data_file,
            "index_file": self.index_file,
            "sample_count": self.sample_count,
            "chunk_count": self.chunk_count,
            "bytes_written": self.bytes_written,
        }
        if self.first_t0_us is not None:
            payload["first_t0_us"] = self.first_t0_us
        if self.last_t0_us is not None:
            payload["last_t0_us"] = self.last_t0_us
        if self.clock_sync is not None:
            payload["clock_sync"] = self.clock_sync.to_json_object()
        return payload

    @classmethod
    def from_mapping(cls, data: JsonObject) -> RawCaptureSensorManifest:
        return cls(
            client_id=_str_from_json(data.get("client_id")),
            sample_rate_hz=_int_from_json(data.get("sample_rate_hz")),
            data_file=_str_from_json(data.get("data_file")),
            index_file=_str_from_json(data.get("index_file")),
            sample_count=_int_from_json(data.get("sample_count")),
            chunk_count=_int_from_json(data.get("chunk_count")),
            bytes_written=_int_from_json(data.get("bytes_written")),
            first_t0_us=_int_or_none(data.get("first_t0_us")),
            last_t0_us=_int_or_none(data.get("last_t0_us")),
            clock_sync=(
                RawCaptureSensorClockSync.from_mapping(clock_sync_raw)
                if is_json_object(clock_sync_raw := data.get("clock_sync"))
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class RawCaptureManifest:
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

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "schema_version": self.schema_version,
            "storage_type": self.storage_type,
            "capture_mode": self.capture_mode,
            "run_id": self.run_id,
            "relative_dir": self.relative_dir,
            "total_samples": self.total_samples,
            "total_bytes": self.total_bytes,
            "created_at": self.created_at,
            "sensors": [sensor.to_json_object() for sensor in self.sensors],
        }
        if self.run_start_monotonic_us is not None:
            payload["run_start_monotonic_us"] = self.run_start_monotonic_us
        if self.sensor_losses:
            payload["sensor_losses"] = [
                sensor_loss.to_json_object() for sensor_loss in self.sensor_losses
            ]
        if self.losses.total_dropped_chunk_count > 0:
            payload["losses"] = self.losses.to_json_object()
        return payload

    @classmethod
    def from_mapping(cls, data: JsonObject) -> RawCaptureManifest:
        sensors_raw = data.get("sensors")
        sensors: list[RawCaptureSensorManifest] = []
        if isinstance(sensors_raw, list):
            for item in sensors_raw:
                if is_json_object(item):
                    sensors.append(RawCaptureSensorManifest.from_mapping(item))
        sensor_losses_raw = data.get("sensor_losses")
        sensor_losses: list[RawCaptureSensorLossStats] = []
        if isinstance(sensor_losses_raw, list):
            for item in sensor_losses_raw:
                if is_json_object(item):
                    sensor_losses.append(RawCaptureSensorLossStats.from_mapping(item))
        losses_raw = data.get("losses")
        losses = (
            RawCaptureLossStats.from_mapping(losses_raw)
            if is_json_object(losses_raw)
            else RawCaptureLossStats()
        )
        return cls(
            schema_version=_int_from_json(data.get("schema_version"), _RAW_CAPTURE_SCHEMA_VERSION),
            storage_type=_str_from_json(data.get("storage_type"), _RAW_CAPTURE_STORAGE_TYPE),
            capture_mode=_str_from_json(data.get("capture_mode"), _RAW_CAPTURE_MODE),
            run_id=_str_from_json(data.get("run_id")),
            relative_dir=_str_from_json(data.get("relative_dir")),
            sensors=tuple(sensors),
            total_samples=_int_from_json(data.get("total_samples")),
            total_bytes=_int_from_json(data.get("total_bytes")),
            created_at=_str_from_json(data.get("created_at")),
            run_start_monotonic_us=_int_or_none(data.get("run_start_monotonic_us")),
            sensor_losses=tuple(sensor_losses),
            losses=losses,
        )

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


@dataclass(frozen=True, slots=True)
class RawCaptureSensorData:
    """Decoded raw waveform stream plus its persisted chunk index."""

    manifest: RawCaptureSensorManifest
    samples_i16: Int16Array
    chunks: tuple[RawCaptureChunkIndex, ...]


@dataclass(frozen=True, slots=True)
class RawCaptureSensorRange:
    """One manifest-aware raw-capture range read with explicit coverage state."""

    client_id: str
    requested_sample_start: int
    requested_sample_count: int
    coverage_state: RawCaptureCoverageState
    samples_i16: Int16Array
    manifest: RawCaptureSensorManifest | None = None
    returned_sample_start: int | None = None
    chunks: tuple[RawCaptureChunkIndex, ...] = ()

    @classmethod
    def missing(
        cls,
        *,
        client_id: str,
        requested_sample_start: int,
        requested_sample_count: int,
    ) -> RawCaptureSensorRange:
        return cls(
            client_id=client_id,
            requested_sample_start=requested_sample_start,
            requested_sample_count=requested_sample_count,
            coverage_state="missing",
            samples_i16=_empty_i16_samples(),
        )

    @property
    def returned_sample_count(self) -> int:
        if self.samples_i16.ndim <= 0:
            return 0
        return int(self.samples_i16.shape[0])

    @property
    def requested_sample_end(self) -> int:
        return self.requested_sample_start + self.requested_sample_count

    @property
    def returned_sample_end(self) -> int | None:
        if self.returned_sample_start is None:
            return None
        return self.returned_sample_start + self.returned_sample_count

    @property
    def has_full_coverage(self) -> bool:
        return self.coverage_state == "full"


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


def _int_or_none(value: JsonValue | object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def _int_from_json(value: JsonValue | object, default: int = 0) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None else default


def _str_from_json(value: JsonValue | object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _empty_i16_samples() -> Int16Array:
    return np.empty((0, 3), dtype=np.int16)
