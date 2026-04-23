"""Typed raw-capture artifact contracts shared by recording and history flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt

from vibesensor.shared.types.json_types import JsonObject, JsonValue, is_json_object

__all__ = [
    "RawCaptureChunk",
    "RawCaptureChunkIndex",
    "RawCaptureManifest",
    "RawCaptureSensorData",
    "RawCaptureSensorManifest",
    "RawCaptureSensorRange",
    "RawRunCapture",
]

type Int16Array = npt.NDArray[np.int16]
type RawCaptureCoverageState = Literal["missing", "empty", "partial", "full"]

_RAW_CAPTURE_SCHEMA_VERSION = 1
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
    schema_version: int = _RAW_CAPTURE_SCHEMA_VERSION
    storage_type: str = _RAW_CAPTURE_STORAGE_TYPE
    capture_mode: str = _RAW_CAPTURE_MODE

    def to_json_object(self) -> JsonObject:
        return {
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

    @classmethod
    def from_mapping(cls, data: JsonObject) -> RawCaptureManifest:
        sensors_raw = data.get("sensors")
        sensors: list[RawCaptureSensorManifest] = []
        if isinstance(sensors_raw, list):
            for item in sensors_raw:
                if is_json_object(item):
                    sensors.append(RawCaptureSensorManifest.from_mapping(item))
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
        )

    def sensor_manifest(self, client_id: str) -> RawCaptureSensorManifest | None:
        for sensor in self.sensors:
            if sensor.client_id == client_id:
                return sensor
        return None


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
