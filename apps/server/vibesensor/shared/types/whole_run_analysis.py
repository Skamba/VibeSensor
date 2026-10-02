"""Shared whole-run post-analysis contracts for window identity, context, and sidecars."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isclose
from typing import Literal

from vibesensor.domain.driving_segment import DrivingPhase
from vibesensor.shared.types.json_contract import JsonContract, require_non_negative
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.raw_capture import RawCaptureManifest
from vibesensor.shared.types.run_schema import RunMetadata

__all__ = [
    "WHOLE_RUN_ARTIFACT_SCHEMA_VERSION",
    "WHOLE_RUN_ARTIFACT_STORAGE_DIR_NAME",
    "WHOLE_RUN_ALGORITHM_VERSIONS",
    "WholeRunArtifactFile",
    "WholeRunArtifactManifest",
    "WholeRunContextCoverage",
    "WholeRunContextInterval",
    "WholeRunContextLoadState",
    "WholeRunContextWindowLabel",
    "WholeRunRpmValidity",
    "WholeRunSpeedContextReason",
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
type WholeRunSpeedContextReason = Literal[
    "speed_unavailable",
    "speed_low",
    "speed_stale",
    "speed_unstable",
    "speed_assumed",
]


@dataclass(frozen=True, slots=True)
class WholeRunWindowPolicy(JsonContract):
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


@dataclass(frozen=True, slots=True)
class WholeRunWindowDescriptor(JsonContract):
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


@dataclass(frozen=True, slots=True)
class WholeRunArtifactFile(JsonContract):
    """One dense whole-run sidecar artifact file owned by a run-level manifest."""

    artifact_key: str
    relative_path: str
    file_format: str
    record_count: int | None = None
    sensor_id: str | None = None


@dataclass(frozen=True, slots=True)
class WholeRunSourceRawSensorManifest(JsonContract):
    """Compact source raw-capture sensor manifest recorded for artifact provenance."""

    client_id: str
    sample_rate_hz: int
    sample_count: int
    chunk_count: int
    bytes_written: int
    sample_rate_proof_state: str


@dataclass(frozen=True, slots=True)
class WholeRunSourceRawManifest(JsonContract):
    """Compact source raw-capture manifest recorded by whole-run artifacts."""

    run_id: str
    relative_dir: str
    total_samples: int
    total_bytes: int
    sensor_count: int
    created_at: str
    sensors: tuple[WholeRunSourceRawSensorManifest, ...] = ()

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
class WholeRunArtifactManifest(JsonContract):
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

    def artifact(self, artifact_key: str) -> WholeRunArtifactFile | None:
        for artifact in self.artifacts:
            if artifact.artifact_key == artifact_key:
                return artifact
        return None

    @property
    def generated_artifact_paths(self) -> dict[str, str]:
        return {artifact.artifact_key: artifact.relative_path for artifact in self.artifacts}


@dataclass(frozen=True, slots=True)
class WholeRunContextWindowLabel(JsonContract):
    """Per-window context keyed to the canonical whole-run ``window_index``."""

    window_index: int
    phase: DrivingPhase
    context_coverage: WholeRunContextCoverage
    speed_validity: WholeRunSpeedValidity
    rpm_validity: WholeRunRpmValidity
    load_state: WholeRunContextLoadState
    segment_index: int | None = None
    speed_kmh: float | None = None
    speed_band: str | None = None
    speed_source: str | None = None
    speed_is_stale: bool = False
    engine_rpm: float | None = None
    engine_rpm_source: str | None = None
    rpm_is_stale: bool = False
    speed_context_reasons: tuple[WholeRunSpeedContextReason, ...] = ()

    def __post_init__(self) -> None:
        require_non_negative(self, "window_index", "segment_index")


@dataclass(frozen=True, slots=True)
class WholeRunContextInterval(JsonContract):
    """Compact segment summary aligned to a contiguous range of whole-run windows."""

    segment_index: int
    phase: DrivingPhase
    load_state: WholeRunContextLoadState
    start_window_index: int
    end_window_index: int
    start_t_s: float | None = None
    end_t_s: float | None = None
    speed_min_kmh: float | None = None
    speed_max_kmh: float | None = None
    speed_band: str | None = None
    full_context_window_count: int = 0
    partial_context_window_count: int = 0
    missing_context_window_count: int = 0

    def __post_init__(self) -> None:
        require_non_negative(
            self,
            "segment_index",
            "start_window_index",
            "full_context_window_count",
            "partial_context_window_count",
            "missing_context_window_count",
        )
        if self.end_window_index < self.start_window_index:
            raise ValueError(
                "whole-run context interval requires end_window_index >= start_window_index"
            )
        if (
            self.start_t_s is not None
            and self.end_t_s is not None
            and self.start_t_s > self.end_t_s
        ):
            raise ValueError("whole-run context interval requires start_t_s <= end_t_s")

    @property
    def window_count(self) -> int:
        return (self.end_window_index - self.start_window_index) + 1
