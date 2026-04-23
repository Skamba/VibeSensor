"""Shared whole-run post-analysis contracts for window identity and sidecar artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose

from vibesensor.shared.types.json_types import JsonObject, JsonValue, is_json_object
from vibesensor.shared.types.run_schema import RunMetadata

__all__ = [
    "WHOLE_RUN_ARTIFACT_SCHEMA_VERSION",
    "WholeRunArtifactFile",
    "WholeRunArtifactManifest",
    "WholeRunWindowDescriptor",
    "WholeRunWindowPolicy",
]

WHOLE_RUN_ARTIFACT_SCHEMA_VERSION = 1
_WHOLE_RUN_ARTIFACT_STORAGE_TYPE = "run-directory-v1"


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
        return float(self.stride_samples) / float(self.sample_rate_hz)

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

    def to_json_object(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "storage_type": self.storage_type,
            "run_id": self.run_id,
            "relative_dir": self.relative_dir,
            "window_policy": self.window_policy.to_json_object(),
            "total_window_count": self.total_window_count,
            "artifacts": [artifact.to_json_object() for artifact in self.artifacts],
            "created_at": self.created_at,
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
        )

    def artifact(self, artifact_key: str) -> WholeRunArtifactFile | None:
        for artifact in self.artifacts:
            if artifact.artifact_key == artifact_key:
                return artifact
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


def _float_from_json(value: JsonValue | object, default: float = 0.0) -> float:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    return default


def _str_from_json(value: JsonValue | object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _str_or_none(value: JsonValue | object) -> str | None:
    return value if isinstance(value, str) else None
