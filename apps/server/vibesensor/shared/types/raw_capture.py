"""Typed raw-capture artifact contracts shared by recording and history flows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol, cast

import numpy as np
import numpy.typing as npt

from vibesensor.shared.types.json_types import JsonObject, JsonValue, is_json_object

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
    "RawCaptureSensorRange",
    "RawRunCapture",
]

type Int16Array = npt.NDArray[np.int16]
type RawCaptureCoverageState = Literal["missing", "empty", "partial", "full"]
type RawCaptureClockDomain = Literal["server_monotonic", "unverified"]
type RawCaptureSampleRateProofState = Literal[
    "declared_only",
    "observed_consistent",
    "timing_inconsistent",
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

type _JsonFieldDecoder = Callable[[JsonObject], object]
type _JsonFieldEncoder = Callable[[object], object]
type _IncludePredicate = Callable[[object], bool]
type _JsonConstructor[T] = Callable[..., T]


class _JsonObjectEncodable(Protocol):
    def to_json_object(self) -> JsonObject: ...


@dataclass(frozen=True, slots=True)
class _JsonFieldSpec:
    payload_key: str
    attr_name: str
    decode: _JsonFieldDecoder
    encode: _JsonFieldEncoder
    include: _IncludePredicate


def _field(
    payload_key: str,
    *,
    attr_name: str | None = None,
    decode: _JsonFieldDecoder,
    encode: _JsonFieldEncoder | None = None,
    include: _IncludePredicate | None = None,
) -> _JsonFieldSpec:
    return _JsonFieldSpec(
        payload_key=payload_key,
        attr_name=attr_name or payload_key,
        decode=decode,
        encode=encode or _identity_json_value,
        include=include or _always_include,
    )


def _always_include(_value: object) -> bool:
    return True


def _include_if_not_none(value: object) -> bool:
    return value is not None


def _include_if_nonempty(value: object) -> bool:
    return bool(value)


def _include_if_loss_events(value: object) -> bool:
    return cast(RawCaptureLossStats, value).total_loss_event_count > 0


def _identity_json_value(value: object) -> object:
    return value


def _encode_json_object(value: object) -> object:
    return cast(_JsonObjectEncodable, value).to_json_object()


def _encode_json_object_list(value: object) -> object:
    return [item.to_json_object() for item in cast(tuple[_JsonObjectEncodable, ...], value)]


def _int_decoder(payload_key: str, default: int = 0) -> _JsonFieldDecoder:
    def decode(data: JsonObject) -> object:
        return _int_from_json(data.get(payload_key), default)

    return decode


def _int_or_none_decoder(payload_key: str) -> _JsonFieldDecoder:
    def decode(data: JsonObject) -> object:
        return _int_or_none(data.get(payload_key))

    return decode


def _str_decoder(payload_key: str, default: str = "") -> _JsonFieldDecoder:
    def decode(data: JsonObject) -> object:
        return _str_from_json(data.get(payload_key), default)

    return decode


def _nested_object_decoder(
    payload_key: str,
    constructor: Callable[[JsonObject], object],
    *,
    default_factory: Callable[[], object],
) -> _JsonFieldDecoder:
    def decode(data: JsonObject) -> object:
        raw = data.get(payload_key)
        return constructor(raw) if is_json_object(raw) else default_factory()

    return decode


def _optional_object_decoder(
    payload_key: str,
    constructor: Callable[[JsonObject], object],
) -> _JsonFieldDecoder:
    def decode(data: JsonObject) -> object:
        raw = data.get(payload_key)
        return constructor(raw) if is_json_object(raw) else None

    return decode


def _tuple_decoder(
    payload_key: str,
    constructor: Callable[[JsonObject], object],
) -> _JsonFieldDecoder:
    def decode(data: JsonObject) -> object:
        raw = data.get(payload_key)
        if not isinstance(raw, list):
            return ()
        return tuple(constructor(item) for item in raw if is_json_object(item))

    return decode


def _json_object_kwargs(
    data: JsonObject,
    specs: tuple[_JsonFieldSpec, ...],
) -> dict[str, object]:
    return {spec.attr_name: spec.decode(data) for spec in specs}


def _build_from_json_object[T](
    data: JsonObject,
    specs: tuple[_JsonFieldSpec, ...],
    constructor: _JsonConstructor[T],
    **overrides: object,
) -> T:
    kwargs = _json_object_kwargs(data, specs)
    kwargs.update(overrides)
    return constructor(**kwargs)


def _project_json_object(source: object, specs: tuple[_JsonFieldSpec, ...]) -> JsonObject:
    payload: dict[str, object] = {}
    for spec in specs:
        value = getattr(source, spec.attr_name)
        if spec.include(value):
            payload[spec.payload_key] = spec.encode(value)
    return cast(JsonObject, payload)


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
        return _project_json_object(self, _RAW_CAPTURE_CHUNK_INDEX_JSON_FIELDS)

    @classmethod
    def from_mapping(cls, data: JsonObject) -> RawCaptureChunkIndex:
        return _build_from_json_object(data, _RAW_CAPTURE_CHUNK_INDEX_JSON_FIELDS, cls)


@dataclass(frozen=True, slots=True)
class RawCaptureLossStats:
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

    def to_json_object(self) -> JsonObject:
        return _project_json_object(self, _RAW_CAPTURE_LOSS_STATS_JSON_FIELDS)

    @classmethod
    def from_mapping(cls, data: JsonObject) -> RawCaptureLossStats:
        return _build_from_json_object(data, _RAW_CAPTURE_LOSS_STATS_JSON_FIELDS, cls)

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
class RawCaptureSensorLossStats:
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

    def to_json_object(self) -> JsonObject:
        return _project_json_object(self, _RAW_CAPTURE_SENSOR_LOSS_STATS_JSON_FIELDS)

    @classmethod
    def from_mapping(cls, data: JsonObject) -> RawCaptureSensorLossStats:
        return _build_from_json_object(data, _RAW_CAPTURE_SENSOR_LOSS_STATS_JSON_FIELDS, cls)


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
        return _project_json_object(self, _RAW_CAPTURE_SENSOR_CLOCK_SYNC_JSON_FIELDS)

    @classmethod
    def from_mapping(cls, data: JsonObject) -> RawCaptureSensorClockSync:
        return _build_from_json_object(data, _RAW_CAPTURE_SENSOR_CLOCK_SYNC_JSON_FIELDS, cls)


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
    declared_sample_rate_hz: int | None = None
    sample_rate_proof_state: RawCaptureSampleRateProofState = "declared_only"

    @property
    def sample_rate_observed(self) -> bool:
        return self.sample_rate_proof_state == "observed_consistent"

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

    def to_json_object(self) -> JsonObject:
        return _project_json_object(self, _RAW_CAPTURE_SENSOR_MANIFEST_JSON_FIELDS)

    @classmethod
    def from_mapping(cls, data: JsonObject) -> RawCaptureSensorManifest:
        kwargs = _json_object_kwargs(data, _RAW_CAPTURE_SENSOR_MANIFEST_JSON_FIELDS)
        sample_rate_hz = cast(int, kwargs["sample_rate_hz"])
        return _build_from_json_object(
            data,
            _RAW_CAPTURE_SENSOR_MANIFEST_JSON_FIELDS,
            cls,
            declared_sample_rate_hz=(
                cast(int | None, kwargs["declared_sample_rate_hz"]) or sample_rate_hz or None
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
        return _project_json_object(self, _RAW_CAPTURE_MANIFEST_JSON_FIELDS)

    @classmethod
    def from_mapping(cls, data: JsonObject) -> RawCaptureManifest:
        return _build_from_json_object(data, _RAW_CAPTURE_MANIFEST_JSON_FIELDS, cls)

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


_RAW_CAPTURE_CHUNK_INDEX_JSON_FIELDS: tuple[_JsonFieldSpec, ...] = (
    _field("sample_start", decode=_int_decoder("sample_start")),
    _field("sample_count", decode=_int_decoder("sample_count")),
    _field("t0_us", decode=_int_decoder("t0_us")),
    _field("byte_offset", decode=_int_decoder("byte_offset")),
)
_RAW_CAPTURE_LOSS_STATS_JSON_FIELDS: tuple[_JsonFieldSpec, ...] = (
    _field(
        "udp_ingest_queue_drop_count",
        decode=_int_decoder("udp_ingest_queue_drop_count"),
    ),
    _field("late_packet_chunk_count", decode=_int_decoder("late_packet_chunk_count")),
    _field(
        "queue_overflow_chunk_count",
        decode=_int_decoder("queue_overflow_chunk_count"),
    ),
    _field("invalid_chunk_count", decode=_int_decoder("invalid_chunk_count")),
    _field("write_error_chunk_count", decode=_int_decoder("write_error_chunk_count")),
)
_RAW_CAPTURE_SENSOR_LOSS_STATS_JSON_FIELDS: tuple[_JsonFieldSpec, ...] = (
    _field("client_id", decode=_str_decoder("client_id")),
    _field(
        "losses",
        decode=_nested_object_decoder(
            "losses",
            RawCaptureLossStats.from_mapping,
            default_factory=RawCaptureLossStats,
        ),
        encode=_encode_json_object,
    ),
)
_RAW_CAPTURE_SENSOR_CLOCK_SYNC_JSON_FIELDS: tuple[_JsonFieldSpec, ...] = (
    _field("clock_domain", decode=_str_decoder("clock_domain", "unverified")),
    _field("proof_state", decode=_str_decoder("proof_state", "missing_sync")),
    _field(
        "observed_monotonic_us",
        decode=_int_or_none_decoder("observed_monotonic_us"),
        include=_include_if_not_none,
    ),
    _field(
        "last_sync_monotonic_us",
        decode=_int_or_none_decoder("last_sync_monotonic_us"),
        include=_include_if_not_none,
    ),
    _field(
        "sync_offset_us",
        decode=_int_or_none_decoder("sync_offset_us"),
        include=_include_if_not_none,
    ),
    _field(
        "sync_rtt_us",
        decode=_int_or_none_decoder("sync_rtt_us"),
        include=_include_if_not_none,
    ),
    _field(
        "max_sync_age_us",
        decode=_int_or_none_decoder("max_sync_age_us"),
        include=_include_if_not_none,
    ),
    _field(
        "max_sync_rtt_us",
        decode=_int_or_none_decoder("max_sync_rtt_us"),
        include=_include_if_not_none,
    ),
)
_RAW_CAPTURE_SENSOR_MANIFEST_JSON_FIELDS: tuple[_JsonFieldSpec, ...] = (
    _field("client_id", decode=_str_decoder("client_id")),
    _field("sample_rate_hz", decode=_int_decoder("sample_rate_hz")),
    _field("data_file", decode=_str_decoder("data_file")),
    _field("index_file", decode=_str_decoder("index_file")),
    _field("sample_count", decode=_int_decoder("sample_count")),
    _field("chunk_count", decode=_int_decoder("chunk_count")),
    _field("bytes_written", decode=_int_decoder("bytes_written")),
    _field(
        "first_t0_us",
        decode=_int_or_none_decoder("first_t0_us"),
        include=_include_if_not_none,
    ),
    _field(
        "last_t0_us",
        decode=_int_or_none_decoder("last_t0_us"),
        include=_include_if_not_none,
    ),
    _field(
        "clock_sync",
        decode=_optional_object_decoder(
            "clock_sync",
            RawCaptureSensorClockSync.from_mapping,
        ),
        encode=_encode_json_object,
        include=_include_if_not_none,
    ),
    _field(
        "declared_sample_rate_hz",
        decode=_int_or_none_decoder("declared_sample_rate_hz"),
        include=_include_if_not_none,
    ),
    _field(
        "sample_rate_proof_state",
        decode=_str_decoder("sample_rate_proof_state", "declared_only"),
    ),
)
_RAW_CAPTURE_MANIFEST_JSON_FIELDS: tuple[_JsonFieldSpec, ...] = (
    _field(
        "schema_version",
        decode=_int_decoder("schema_version", _RAW_CAPTURE_SCHEMA_VERSION),
    ),
    _field(
        "storage_type",
        decode=_str_decoder("storage_type", _RAW_CAPTURE_STORAGE_TYPE),
    ),
    _field(
        "capture_mode",
        decode=_str_decoder("capture_mode", _RAW_CAPTURE_MODE),
    ),
    _field("run_id", decode=_str_decoder("run_id")),
    _field("relative_dir", decode=_str_decoder("relative_dir")),
    _field(
        "sensors",
        decode=_tuple_decoder("sensors", RawCaptureSensorManifest.from_mapping),
        encode=_encode_json_object_list,
    ),
    _field("total_samples", decode=_int_decoder("total_samples")),
    _field("total_bytes", decode=_int_decoder("total_bytes")),
    _field("created_at", decode=_str_decoder("created_at")),
    _field(
        "run_start_monotonic_us",
        decode=_int_or_none_decoder("run_start_monotonic_us"),
        include=_include_if_not_none,
    ),
    _field(
        "sensor_losses",
        decode=_tuple_decoder("sensor_losses", RawCaptureSensorLossStats.from_mapping),
        encode=_encode_json_object_list,
        include=_include_if_nonempty,
    ),
    _field(
        "losses",
        decode=_nested_object_decoder(
            "losses",
            RawCaptureLossStats.from_mapping,
            default_factory=RawCaptureLossStats,
        ),
        encode=_encode_json_object,
        include=_include_if_loss_events,
    ),
)


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
