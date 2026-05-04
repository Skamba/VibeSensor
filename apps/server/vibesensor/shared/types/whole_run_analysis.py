"""Shared whole-run post-analysis contracts for window identity, context, and sidecars."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isclose
from typing import Literal, cast

from vibesensor.domain import DrivingPhase
from vibesensor.shared.types.json_types import JsonObject, JsonValue, is_json_object
from vibesensor.shared.types.raw_capture import RawCaptureManifest
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.whole_run_json_helpers import (
    coerce_float_or_default as _float_from_json,
)
from vibesensor.shared.types.whole_run_json_helpers import (
    coerce_float_or_none as _float_or_none,
)
from vibesensor.shared.types.whole_run_json_helpers import (
    coerce_int_or_default as _int_from_json,
)
from vibesensor.shared.types.whole_run_json_helpers import (
    coerce_int_or_none as _int_or_none,
)
from vibesensor.shared.types.whole_run_json_helpers import (
    json_text_or_default as _str_from_json,
)
from vibesensor.shared.types.whole_run_json_helpers import (
    json_text_or_none as _str_or_none,
)

__all__ = [
    "WHOLE_RUN_ARTIFACT_SCHEMA_VERSION",
    "WHOLE_RUN_ARTIFACT_STORAGE_DIR_NAME",
    "WHOLE_RUN_ALGORITHM_VERSIONS",
    "WHOLE_RUN_CONTEXT_COVERAGE_VALUES",
    "WHOLE_RUN_CONTEXT_LOAD_STATE_VALUES",
    "WHOLE_RUN_RPM_VALIDITY_VALUES",
    "WHOLE_RUN_SPEED_VALIDITY_VALUES",
    "WholeRunArtifactFile",
    "WholeRunArtifactManifest",
    "WholeRunContextCoverage",
    "WholeRunContextInterval",
    "WholeRunContextLoadState",
    "WholeRunContextWindowLabel",
    "WholeRunRpmValidity",
    "WholeRunSpeedValidity",
    "WholeRunSourceRawManifest",
    "WholeRunSourceRawSensorManifest",
    "WholeRunWindowDescriptor",
    "WholeRunWindowPolicy",
]

WHOLE_RUN_ARTIFACT_SCHEMA_VERSION = 1
WHOLE_RUN_ARTIFACT_STORAGE_DIR_NAME = "whole-run-artifacts"
_WHOLE_RUN_ARTIFACT_STORAGE_TYPE = "run-directory-v1"
WHOLE_RUN_ALGORITHM_VERSIONS: JsonObject = {
    "whole_run_artifact_manifest": 1,
    "whole_run_spectra": 1,
    "whole_run_context": 1,
    "whole_run_order_traces": 1,
    "whole_run_order_trace_summaries": 1,
    "whole_run_order_family_summaries": 1,
    "whole_run_spatial_coherence": 1,
    "whole_run_diagnosis_summaries": 1,
}

type WholeRunContextCoverage = Literal["full", "partial", "missing"]
type WholeRunSpeedValidity = Literal["measured", "assumed", "missing"]
type WholeRunRpmValidity = Literal["measured", "estimated", "missing"]
type WholeRunContextLoadState = Literal["idle", "steady", "transient", "unknown"]

WHOLE_RUN_CONTEXT_COVERAGE_VALUES: frozenset[WholeRunContextCoverage] = frozenset(
    {"full", "partial", "missing"}
)
WHOLE_RUN_SPEED_VALIDITY_VALUES: frozenset[WholeRunSpeedValidity] = frozenset(
    {"measured", "assumed", "missing"}
)
WHOLE_RUN_RPM_VALIDITY_VALUES: frozenset[WholeRunRpmValidity] = frozenset(
    {"measured", "estimated", "missing"}
)
WHOLE_RUN_CONTEXT_LOAD_STATE_VALUES: frozenset[WholeRunContextLoadState] = frozenset(
    {"idle", "steady", "transient", "unknown"}
)


@dataclass(frozen=True, slots=True)
class WholeRunWindowPolicy:
    """Canonical sample-space policy shared by all whole-run window planners."""

    sample_rate_hz: int
    window_size_samples: int
    stride_samples: int
    overlap_samples: int
    feature_interval_s: float

    @classmethod
    def from_metadata(cls, metadata: RunMetadata) -> WholeRunWindowPolicy:
        sample_rate_hz = int(metadata.raw_sample_rate_hz or 0)
        if sample_rate_hz <= 0:
            raise ValueError("whole-run window policy requires raw_sample_rate_hz")
        window_size_samples = int(metadata.fft_window_size_samples or 0)
        if window_size_samples <= 0:
            raise ValueError("whole-run window policy requires fft_window_size_samples")
        feature_interval_s = float(metadata.feature_interval_s or 0.0)
        if feature_interval_s <= 0.0:
            raise ValueError("whole-run window policy requires feature_interval_s")
        raw_stride_samples = feature_interval_s * float(sample_rate_hz)
        stride_samples = int(round(raw_stride_samples))
        if stride_samples <= 0 or not isclose(
            raw_stride_samples,
            float(stride_samples),
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "whole-run window policy requires feature_interval_s * raw_sample_rate_hz "
                "to resolve to an integral sample stride"
            )
        if stride_samples > window_size_samples:
            raise ValueError(
                "whole-run window policy requires stride_samples <= window_size_samples"
            )
        return cls(
            sample_rate_hz=sample_rate_hz,
            window_size_samples=window_size_samples,
            stride_samples=stride_samples,
            overlap_samples=window_size_samples - stride_samples,
            feature_interval_s=feature_interval_s,
        )

    @property
    def window_duration_s(self) -> float:
        return float(self.window_size_samples) / float(self.sample_rate_hz)

    @property
    def stride_duration_s(self) -> float:
        return float(self.feature_interval_s)

    def to_json_object(self) -> JsonObject:
        return {
            "sample_rate_hz": self.sample_rate_hz,
            "window_size_samples": self.window_size_samples,
            "stride_samples": self.stride_samples,
            "overlap_samples": self.overlap_samples,
            "feature_interval_s": self.feature_interval_s,
        }

    @classmethod
    def from_mapping(cls, data: JsonObject) -> WholeRunWindowPolicy:
        return cls(
            sample_rate_hz=_int_from_json(data.get("sample_rate_hz")),
            window_size_samples=_int_from_json(data.get("window_size_samples")),
            stride_samples=_int_from_json(data.get("stride_samples")),
            overlap_samples=_int_from_json(data.get("overlap_samples")),
            feature_interval_s=_float_from_json(data.get("feature_interval_s")),
        )


@dataclass(frozen=True, slots=True)
class WholeRunWindowDescriptor:
    """Deterministic whole-run window identity used across downstream artifacts."""

    window_index: int
    sample_start: int
    sample_end: int
    center_sample: int
    start_t_s: float
    end_t_s: float
    center_t_s: float

    @classmethod
    def from_policy(
        cls,
        *,
        window_index: int,
        sample_start: int,
        policy: WholeRunWindowPolicy,
    ) -> WholeRunWindowDescriptor:
        if window_index < 0:
            raise ValueError("whole-run window descriptor requires window_index >= 0")
        if sample_start < 0:
            raise ValueError("whole-run window descriptor requires sample_start >= 0")
        sample_end = sample_start + policy.window_size_samples
        center_sample = sample_start + (policy.window_size_samples // 2)
        sample_rate_hz = float(policy.sample_rate_hz)
        return cls(
            window_index=window_index,
            sample_start=sample_start,
            sample_end=sample_end,
            center_sample=center_sample,
            start_t_s=float(sample_start) / sample_rate_hz,
            end_t_s=float(sample_end) / sample_rate_hz,
            center_t_s=float(center_sample) / sample_rate_hz,
        )

    @property
    def sample_count(self) -> int:
        return self.sample_end - self.sample_start

    def to_json_object(self) -> JsonObject:
        return {
            "window_index": self.window_index,
            "sample_start": self.sample_start,
            "sample_end": self.sample_end,
            "center_sample": self.center_sample,
            "start_t_s": self.start_t_s,
            "end_t_s": self.end_t_s,
            "center_t_s": self.center_t_s,
        }

    @classmethod
    def from_mapping(cls, data: JsonObject) -> WholeRunWindowDescriptor:
        return cls(
            window_index=_int_from_json(data.get("window_index")),
            sample_start=_int_from_json(data.get("sample_start")),
            sample_end=_int_from_json(data.get("sample_end")),
            center_sample=_int_from_json(data.get("center_sample")),
            start_t_s=_float_from_json(data.get("start_t_s")),
            end_t_s=_float_from_json(data.get("end_t_s")),
            center_t_s=_float_from_json(data.get("center_t_s")),
        )


@dataclass(frozen=True, slots=True)
class WholeRunArtifactFile:
    """One dense whole-run sidecar artifact file owned by a run-level manifest."""

    artifact_key: str
    relative_path: str
    file_format: str
    record_count: int | None = None
    sensor_id: str | None = None

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "artifact_key": self.artifact_key,
            "relative_path": self.relative_path,
            "file_format": self.file_format,
        }
        if self.record_count is not None:
            payload["record_count"] = self.record_count
        if self.sensor_id is not None:
            payload["sensor_id"] = self.sensor_id
        return payload

    @classmethod
    def from_mapping(cls, data: JsonObject) -> WholeRunArtifactFile:
        return cls(
            artifact_key=_str_from_json(data.get("artifact_key")),
            relative_path=_str_from_json(data.get("relative_path")),
            file_format=_str_from_json(data.get("file_format")),
            record_count=_int_or_none(data.get("record_count")),
            sensor_id=_str_or_none(data.get("sensor_id")),
        )


@dataclass(frozen=True, slots=True)
class WholeRunSourceRawSensorManifest:
    """Compact source raw-capture sensor manifest recorded for artifact provenance."""

    client_id: str
    sample_rate_hz: int
    sample_count: int
    chunk_count: int
    bytes_written: int
    sample_rate_proof_state: str

    def to_json_object(self) -> JsonObject:
        return {
            "client_id": self.client_id,
            "sample_rate_hz": self.sample_rate_hz,
            "sample_count": self.sample_count,
            "chunk_count": self.chunk_count,
            "bytes_written": self.bytes_written,
            "sample_rate_proof_state": self.sample_rate_proof_state,
        }

    @classmethod
    def from_mapping(cls, data: JsonObject) -> WholeRunSourceRawSensorManifest:
        return cls(
            client_id=_str_from_json(data.get("client_id")),
            sample_rate_hz=_int_from_json(data.get("sample_rate_hz")),
            sample_count=_int_from_json(data.get("sample_count")),
            chunk_count=_int_from_json(data.get("chunk_count")),
            bytes_written=_int_from_json(data.get("bytes_written")),
            sample_rate_proof_state=_str_from_json(data.get("sample_rate_proof_state")),
        )


@dataclass(frozen=True, slots=True)
class WholeRunSourceRawManifest:
    """Compact source raw-capture manifest recorded by whole-run artifacts."""

    run_id: str
    relative_dir: str
    total_samples: int
    total_bytes: int
    sensor_count: int
    created_at: str
    sensors: tuple[WholeRunSourceRawSensorManifest, ...] = ()

    def to_json_object(self) -> JsonObject:
        return {
            "run_id": self.run_id,
            "relative_dir": self.relative_dir,
            "total_samples": self.total_samples,
            "total_bytes": self.total_bytes,
            "sensor_count": self.sensor_count,
            "created_at": self.created_at,
            "sensors": [sensor.to_json_object() for sensor in self.sensors],
        }

    @classmethod
    def from_mapping(cls, data: JsonObject) -> WholeRunSourceRawManifest:
        sensors_raw = data.get("sensors")
        sensors: list[WholeRunSourceRawSensorManifest] = []
        if isinstance(sensors_raw, list):
            for item in sensors_raw:
                if is_json_object(item):
                    sensors.append(WholeRunSourceRawSensorManifest.from_mapping(item))
        return cls(
            run_id=_str_from_json(data.get("run_id")),
            relative_dir=_str_from_json(data.get("relative_dir")),
            total_samples=_int_from_json(data.get("total_samples")),
            total_bytes=_int_from_json(data.get("total_bytes")),
            sensor_count=_int_from_json(data.get("sensor_count")),
            created_at=_str_from_json(data.get("created_at")),
            sensors=tuple(sensors),
        )

    @classmethod
    def from_raw_capture_manifest(
        cls,
        manifest: RawCaptureManifest,
    ) -> WholeRunSourceRawManifest:
        sensors = tuple(
            WholeRunSourceRawSensorManifest(
                client_id=sensor.client_id,
                sample_rate_hz=int(sensor.sample_rate_hz),
                sample_count=int(sensor.sample_count),
                chunk_count=int(sensor.chunk_count),
                bytes_written=int(sensor.bytes_written),
                sample_rate_proof_state=str(sensor.sample_rate_proof_state),
            )
            for sensor in sorted(manifest.sensors, key=lambda item: item.client_id)
        )
        return cls(
            run_id=manifest.run_id,
            relative_dir=manifest.relative_dir,
            total_samples=int(manifest.total_samples),
            total_bytes=int(manifest.total_bytes),
            sensor_count=len(sensors),
            created_at=manifest.created_at,
            sensors=sensors,
        )


@dataclass(frozen=True, slots=True)
class WholeRunArtifactManifest:
    """Run-level manifest for dense whole-run artifacts stored outside analysis_json."""

    run_id: str
    relative_dir: str
    window_policy: WholeRunWindowPolicy
    total_window_count: int
    artifacts: tuple[WholeRunArtifactFile, ...]
    created_at: str
    schema_version: int = WHOLE_RUN_ARTIFACT_SCHEMA_VERSION
    storage_type: str = _WHOLE_RUN_ARTIFACT_STORAGE_TYPE
    algorithm_versions: JsonObject = field(default_factory=dict)
    configuration: JsonObject = field(default_factory=dict)
    source_raw_manifests: tuple[WholeRunSourceRawManifest, ...] = ()

    def to_json_object(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "storage_type": self.storage_type,
            "run_id": self.run_id,
            "relative_dir": self.relative_dir,
            "window_policy": self.window_policy.to_json_object(),
            "total_window_count": self.total_window_count,
            "artifacts": [artifact.to_json_object() for artifact in self.artifacts],
            "generated_artifact_paths": {
                artifact.artifact_key: artifact.relative_path for artifact in self.artifacts
            },
            "created_at": self.created_at,
            "algorithm_versions": dict(self.algorithm_versions),
            "configuration": dict(self.configuration),
            "source_raw_manifests": [
                manifest.to_json_object() for manifest in self.source_raw_manifests
            ],
        }

    @classmethod
    def from_mapping(cls, data: JsonObject) -> WholeRunArtifactManifest:
        policy_data = data.get("window_policy")
        if not is_json_object(policy_data):
            raise ValueError("whole-run artifact manifest requires window_policy")
        artifacts_raw = data.get("artifacts")
        artifacts: list[WholeRunArtifactFile] = []
        if isinstance(artifacts_raw, list):
            for item in artifacts_raw:
                if is_json_object(item):
                    artifacts.append(WholeRunArtifactFile.from_mapping(item))
        source_manifests_raw = data.get("source_raw_manifests")
        source_manifests: list[WholeRunSourceRawManifest] = []
        if isinstance(source_manifests_raw, list):
            for item in source_manifests_raw:
                if is_json_object(item):
                    source_manifests.append(WholeRunSourceRawManifest.from_mapping(item))
        algorithm_versions_raw = data.get("algorithm_versions")
        configuration_raw = data.get("configuration")
        return cls(
            schema_version=_int_from_json(
                data.get("schema_version"),
                WHOLE_RUN_ARTIFACT_SCHEMA_VERSION,
            ),
            storage_type=_str_from_json(data.get("storage_type"), _WHOLE_RUN_ARTIFACT_STORAGE_TYPE),
            run_id=_str_from_json(data.get("run_id")),
            relative_dir=_str_from_json(data.get("relative_dir")),
            window_policy=WholeRunWindowPolicy.from_mapping(policy_data),
            total_window_count=_int_from_json(data.get("total_window_count")),
            artifacts=tuple(artifacts),
            created_at=_str_from_json(data.get("created_at")),
            algorithm_versions=(
                dict(algorithm_versions_raw) if is_json_object(algorithm_versions_raw) else {}
            ),
            configuration=dict(configuration_raw) if is_json_object(configuration_raw) else {},
            source_raw_manifests=tuple(source_manifests),
        )

    def artifact(self, artifact_key: str) -> WholeRunArtifactFile | None:
        for artifact in self.artifacts:
            if artifact.artifact_key == artifact_key:
                return artifact
        return None

    @property
    def generated_artifact_paths(self) -> dict[str, str]:
        return {artifact.artifact_key: artifact.relative_path for artifact in self.artifacts}


@dataclass(frozen=True, slots=True)
class WholeRunContextWindowLabel:
    """Per-window context keyed to the canonical whole-run ``window_index``."""

    window_index: int
    segment_index: int | None
    phase: DrivingPhase
    context_coverage: WholeRunContextCoverage
    speed_validity: WholeRunSpeedValidity
    rpm_validity: WholeRunRpmValidity
    load_state: WholeRunContextLoadState
    speed_kmh: float | None = None
    speed_band: str | None = None
    speed_source: str | None = None
    speed_is_stale: bool = False
    engine_rpm: float | None = None
    engine_rpm_source: str | None = None
    rpm_is_stale: bool = False

    def __post_init__(self) -> None:
        if self.window_index < 0:
            raise ValueError("whole-run context window label requires window_index >= 0")
        if self.segment_index is not None and self.segment_index < 0:
            raise ValueError("whole-run context window label requires segment_index >= 0")

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "window_index": self.window_index,
            "phase": self.phase.value,
            "context_coverage": self.context_coverage,
            "speed_validity": self.speed_validity,
            "rpm_validity": self.rpm_validity,
            "load_state": self.load_state,
            "speed_is_stale": self.speed_is_stale,
            "rpm_is_stale": self.rpm_is_stale,
        }
        if self.segment_index is not None:
            payload["segment_index"] = self.segment_index
        if self.speed_kmh is not None:
            payload["speed_kmh"] = self.speed_kmh
        if self.speed_band is not None:
            payload["speed_band"] = self.speed_band
        if self.speed_source is not None:
            payload["speed_source"] = self.speed_source
        if self.engine_rpm is not None:
            payload["engine_rpm"] = self.engine_rpm
        if self.engine_rpm_source is not None:
            payload["engine_rpm_source"] = self.engine_rpm_source
        return payload

    @classmethod
    def from_mapping(cls, data: JsonObject) -> WholeRunContextWindowLabel:
        return cls(
            window_index=_int_from_json(data.get("window_index")),
            segment_index=_int_or_none(data.get("segment_index")),
            phase=_driving_phase_from_json(data.get("phase")),
            context_coverage=_context_coverage_from_json(data.get("context_coverage")),
            speed_validity=_speed_validity_from_json(data.get("speed_validity")),
            rpm_validity=_rpm_validity_from_json(data.get("rpm_validity")),
            load_state=_load_state_from_json(data.get("load_state")),
            speed_kmh=_float_or_none(data.get("speed_kmh")),
            speed_band=_str_or_none(data.get("speed_band")),
            speed_source=_str_or_none(data.get("speed_source")),
            speed_is_stale=_bool_from_json(data.get("speed_is_stale")),
            engine_rpm=_float_or_none(data.get("engine_rpm")),
            engine_rpm_source=_str_or_none(data.get("engine_rpm_source")),
            rpm_is_stale=_bool_from_json(data.get("rpm_is_stale")),
        )


@dataclass(frozen=True, slots=True)
class WholeRunContextInterval:
    """Compact segment summary aligned to a contiguous range of whole-run windows."""

    segment_index: int
    phase: DrivingPhase
    load_state: WholeRunContextLoadState
    start_window_index: int
    end_window_index: int
    start_t_s: float | None
    end_t_s: float | None
    speed_min_kmh: float | None = None
    speed_max_kmh: float | None = None
    speed_band: str | None = None
    full_context_window_count: int = 0
    partial_context_window_count: int = 0
    missing_context_window_count: int = 0

    def __post_init__(self) -> None:
        if self.segment_index < 0:
            raise ValueError("whole-run context interval requires segment_index >= 0")
        if self.start_window_index < 0:
            raise ValueError("whole-run context interval requires start_window_index >= 0")
        if self.end_window_index < self.start_window_index:
            raise ValueError(
                "whole-run context interval requires end_window_index >= start_window_index"
            )
        for field_name in (
            "full_context_window_count",
            "partial_context_window_count",
            "missing_context_window_count",
        ):
            if getattr(self, field_name) < 0:
                raise ValueError(f"whole-run context interval requires {field_name} >= 0")
        if (
            self.start_t_s is not None
            and self.end_t_s is not None
            and self.start_t_s > self.end_t_s
        ):
            raise ValueError("whole-run context interval requires start_t_s <= end_t_s")

    @property
    def window_count(self) -> int:
        return (self.end_window_index - self.start_window_index) + 1

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "segment_index": self.segment_index,
            "phase": self.phase.value,
            "load_state": self.load_state,
            "start_window_index": self.start_window_index,
            "end_window_index": self.end_window_index,
            "full_context_window_count": self.full_context_window_count,
            "partial_context_window_count": self.partial_context_window_count,
            "missing_context_window_count": self.missing_context_window_count,
        }
        if self.start_t_s is not None:
            payload["start_t_s"] = self.start_t_s
        if self.end_t_s is not None:
            payload["end_t_s"] = self.end_t_s
        if self.speed_min_kmh is not None:
            payload["speed_min_kmh"] = self.speed_min_kmh
        if self.speed_max_kmh is not None:
            payload["speed_max_kmh"] = self.speed_max_kmh
        if self.speed_band is not None:
            payload["speed_band"] = self.speed_band
        return payload

    @classmethod
    def from_mapping(cls, data: JsonObject) -> WholeRunContextInterval:
        return cls(
            segment_index=_int_from_json(data.get("segment_index")),
            phase=_driving_phase_from_json(data.get("phase")),
            load_state=_load_state_from_json(data.get("load_state")),
            start_window_index=_int_from_json(data.get("start_window_index")),
            end_window_index=_int_from_json(data.get("end_window_index")),
            start_t_s=_float_or_none(data.get("start_t_s")),
            end_t_s=_float_or_none(data.get("end_t_s")),
            speed_min_kmh=_float_or_none(data.get("speed_min_kmh")),
            speed_max_kmh=_float_or_none(data.get("speed_max_kmh")),
            speed_band=_str_or_none(data.get("speed_band")),
            full_context_window_count=_int_from_json(data.get("full_context_window_count")),
            partial_context_window_count=_int_from_json(data.get("partial_context_window_count")),
            missing_context_window_count=_int_from_json(data.get("missing_context_window_count")),
        )


def _driving_phase_from_json(value: JsonValue | object) -> DrivingPhase:
    raw = _str_or_none(value)
    if raw is None:
        return DrivingPhase.SPEED_UNKNOWN
    try:
        return DrivingPhase(raw)
    except ValueError:
        return DrivingPhase.SPEED_UNKNOWN


def _bool_from_json(value: JsonValue | object) -> bool:
    return value is True


def _context_coverage_from_json(value: JsonValue | object) -> WholeRunContextCoverage:
    raw = _str_or_none(value)
    if raw in WHOLE_RUN_CONTEXT_COVERAGE_VALUES:
        return cast(WholeRunContextCoverage, raw)
    return "missing"


def _speed_validity_from_json(value: JsonValue | object) -> WholeRunSpeedValidity:
    raw = _str_or_none(value)
    if raw in WHOLE_RUN_SPEED_VALIDITY_VALUES:
        return cast(WholeRunSpeedValidity, raw)
    return "missing"


def _rpm_validity_from_json(value: JsonValue | object) -> WholeRunRpmValidity:
    raw = _str_or_none(value)
    if raw in WHOLE_RUN_RPM_VALIDITY_VALUES:
        return cast(WholeRunRpmValidity, raw)
    return "missing"


def _load_state_from_json(value: JsonValue | object) -> WholeRunContextLoadState:
    raw = _str_or_none(value)
    if raw in WHOLE_RUN_CONTEXT_LOAD_STATE_VALUES:
        return cast(WholeRunContextLoadState, raw)
    return "unknown"
