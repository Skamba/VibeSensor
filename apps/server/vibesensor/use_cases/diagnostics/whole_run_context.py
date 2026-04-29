"""Whole-run speed and RPM normalization onto the canonical window grid."""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

from vibesensor.domain import DrivingPhase, speed_bin_label
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.whole_run_analysis import (
    WHOLE_RUN_ARTIFACT_STORAGE_DIR_NAME,
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunContextCoverage,
    WholeRunContextInterval,
    WholeRunContextLoadState,
    WholeRunContextWindowLabel,
    WholeRunRpmValidity,
    WholeRunSpeedValidity,
)
from vibesensor.use_cases.diagnostics._jsonl_sidecars import (
    jsonl_bytes_from_objects,
    jsonl_objects_from_bytes,
)

from ._reference_resolution import _effective_engine_rpm, _tire_reference_from_context
from ._types import Sample
from .phase_segmentation import segment_whole_run_context
from .whole_run_windows import WholeRunWindowPlan, plan_whole_run_windows

__all__ = [
    "WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY",
    "WholeRunContextArtifactBundle",
    "build_whole_run_context_artifact_bundle",
    "normalize_whole_run_context_labels",
    "whole_run_context_labels_from_jsonl_bytes",
    "whole_run_context_labels_to_jsonl_bytes",
]

WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY = "context-window-labels"
_WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_PATH = "context/window-labels.jsonl"

_SPEED_VALIDITY_RANK: dict[WholeRunSpeedValidity, int] = {
    "missing": 0,
    "assumed": 1,
    "measured": 2,
}
_RPM_VALIDITY_RANK: dict[WholeRunRpmValidity, int] = {
    "missing": 0,
    "estimated": 1,
    "measured": 2,
}


@dataclass(frozen=True, slots=True)
class _SpeedObservation:
    t_s: float
    speed_kmh: float
    speed_source: str
    speed_validity: WholeRunSpeedValidity


@dataclass(frozen=True, slots=True)
class _RpmObservation:
    t_s: float
    engine_rpm: float
    engine_rpm_source: str
    rpm_validity: WholeRunRpmValidity


@dataclass(frozen=True, slots=True)
class WholeRunContextArtifactBundle:
    """Whole-run context sidecar payload plus compact persisted intervals."""

    manifest: WholeRunArtifactManifest
    artifact_contents: dict[str, bytes]
    labels: tuple[WholeRunContextWindowLabel, ...]
    intervals: tuple[WholeRunContextInterval, ...]


def build_whole_run_context_artifact_bundle(
    *,
    run_id: str,
    metadata: RunMetadata,
    samples: Sequence[Sample],
    total_sample_count: int | None = None,
    window_plan: WholeRunWindowPlan | None = None,
    created_at: str | None = None,
) -> WholeRunContextArtifactBundle:
    """Build whole-run context labels and compact segments for persistence."""

    if window_plan is None:
        if total_sample_count is None:
            raise ValueError("whole-run context builder requires total_sample_count or window_plan")
        window_plan = plan_whole_run_windows(
            metadata=metadata,
            total_sample_count=total_sample_count,
        )
    labels = normalize_whole_run_context_labels(
        metadata=metadata,
        samples=samples,
        window_plan=window_plan,
    )
    segmentation = segment_whole_run_context(labels=labels, window_plan=window_plan)
    artifact_file = WholeRunArtifactFile(
        artifact_key=WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY,
        relative_path=_WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_PATH,
        file_format="jsonl",
        record_count=len(segmentation.labels),
    )
    manifest = WholeRunArtifactManifest(
        run_id=run_id,
        relative_dir=f"{WHOLE_RUN_ARTIFACT_STORAGE_DIR_NAME}/{run_id}",
        window_policy=window_plan.policy,
        total_window_count=window_plan.total_window_count,
        artifacts=(artifact_file,),
        created_at=created_at or utc_now_iso(),
    )
    return WholeRunContextArtifactBundle(
        manifest=manifest,
        artifact_contents={
            WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY: whole_run_context_labels_to_jsonl_bytes(
                segmentation.labels
            )
        },
        labels=segmentation.labels,
        intervals=segmentation.intervals,
    )


def whole_run_context_labels_to_jsonl_bytes(
    labels: Sequence[WholeRunContextWindowLabel],
) -> bytes:
    """Serialize whole-run context labels into the sidecar JSONL format."""

    return jsonl_bytes_from_objects(labels)


def whole_run_context_labels_from_jsonl_bytes(
    payload: bytes,
) -> tuple[WholeRunContextWindowLabel, ...]:
    """Reconstruct persisted whole-run context labels from sidecar JSONL bytes."""

    return jsonl_objects_from_bytes(
        payload,
        context="whole-run context labels",
        line_description="whole-run context label line",
        from_mapping=WholeRunContextWindowLabel.from_mapping,
    )


def normalize_whole_run_context_labels(
    *,
    metadata: RunMetadata,
    samples: Sequence[Sample],
    window_plan: WholeRunWindowPlan,
) -> tuple[WholeRunContextWindowLabel, ...]:
    """Project persisted speed/RPM context onto the canonical whole-run grid.

    The join target is each window's center time so the resulting label reflects
    the middle of the analyzed raw window rather than just its trailing edge.
    """

    speed_observations, rpm_observations = _collect_context_observations(
        metadata=metadata,
        samples=samples,
    )
    freshness_limit_s = max(1e-9, window_plan.policy.stride_duration_s)
    labels: list[WholeRunContextWindowLabel] = []
    for window in window_plan.windows:
        speed_index = _nearest_observation_index(
            target_t_s=window.center_t_s,
            observation_times=[observation.t_s for observation in speed_observations],
        )
        rpm_index = _nearest_observation_index(
            target_t_s=window.center_t_s,
            observation_times=[observation.t_s for observation in rpm_observations],
        )
        speed_observation = speed_observations[speed_index] if speed_index is not None else None
        rpm_observation = rpm_observations[rpm_index] if rpm_index is not None else None
        speed_age_s = (
            abs(speed_observation.t_s - window.center_t_s)
            if speed_observation is not None
            else None
        )
        rpm_age_s = (
            abs(rpm_observation.t_s - window.center_t_s) if rpm_observation is not None else None
        )
        speed_source = speed_observation.speed_source if speed_observation is not None else None
        engine_rpm_source = (
            rpm_observation.engine_rpm_source if rpm_observation is not None else None
        )
        speed_is_stale = (
            speed_age_s is not None and speed_age_s > freshness_limit_s
        ) or _speed_source_requires_stale_context(speed_source)
        rpm_is_stale = (rpm_age_s is not None and rpm_age_s > freshness_limit_s) or (
            speed_is_stale and engine_rpm_source == "estimated_from_speed_and_ratios"
        )
        speed_kmh = speed_observation.speed_kmh if speed_observation is not None else None
        speed_validity = (
            speed_observation.speed_validity if speed_observation is not None else "missing"
        )
        rpm_validity = rpm_observation.rpm_validity if rpm_observation is not None else "missing"
        phase, load_state = _baseline_phase_state(
            speed_kmh=speed_kmh,
            speed_validity=speed_validity,
            speed_is_stale=speed_is_stale,
        )
        labels.append(
            WholeRunContextWindowLabel(
                window_index=window.window_index,
                segment_index=None,
                phase=phase,
                context_coverage=_context_coverage(
                    speed_validity=speed_validity,
                    speed_is_stale=speed_is_stale,
                    rpm_validity=rpm_validity,
                    rpm_is_stale=rpm_is_stale,
                ),
                speed_validity=speed_validity,
                rpm_validity=rpm_validity,
                load_state=load_state,
                speed_kmh=speed_kmh,
                speed_band=(
                    speed_bin_label(speed_kmh)
                    if speed_kmh is not None and not speed_is_stale
                    else None
                ),
                speed_source=speed_source,
                speed_is_stale=speed_is_stale,
                engine_rpm=(rpm_observation.engine_rpm if rpm_observation is not None else None),
                engine_rpm_source=engine_rpm_source,
                rpm_is_stale=rpm_is_stale,
            )
        )
    return tuple(labels)


def _collect_context_observations(
    *,
    metadata: RunMetadata,
    samples: Sequence[Sample],
) -> tuple[tuple[_SpeedObservation, ...], tuple[_RpmObservation, ...]]:
    samples_by_t_s: dict[float, list[Sample]] = defaultdict(list)
    for sample in samples:
        t_s = sample.t_s
        if t_s is None or not isfinite(t_s) or t_s < 0.0:
            continue
        samples_by_t_s[float(t_s)].append(sample)
    tire_circumference_m, _ = _tire_reference_from_context(metadata)
    speed_observations: list[_SpeedObservation] = []
    rpm_observations: list[_RpmObservation] = []
    for t_s in sorted(samples_by_t_s):
        group = samples_by_t_s[t_s]
        speed_observation = _best_speed_observation(t_s=t_s, samples=group)
        if speed_observation is not None:
            speed_observations.append(speed_observation)
        rpm_observation = _best_rpm_observation(
            t_s=t_s,
            samples=group,
            metadata=metadata,
            tire_circumference_m=tire_circumference_m,
        )
        if rpm_observation is not None:
            rpm_observations.append(rpm_observation)
    return tuple(speed_observations), tuple(rpm_observations)


def _best_speed_observation(
    *,
    t_s: float,
    samples: Sequence[Sample],
) -> _SpeedObservation | None:
    best: _SpeedObservation | None = None
    best_key: tuple[int, int, str] | None = None
    for sample in samples:
        speed_kmh = sample.speed_kmh
        if speed_kmh is None or not isfinite(speed_kmh) or speed_kmh < 0.0:
            continue
        speed_source = str(sample.speed_source or "none")
        speed_validity = _speed_validity_for_source(speed_source)
        if speed_validity == "missing":
            continue
        key = (
            _SPEED_VALIDITY_RANK[speed_validity],
            _speed_source_rank(speed_source),
            str(sample.client_id),
        )
        if best_key is None or key > best_key:
            best_key = key
            best = _SpeedObservation(
                t_s=t_s,
                speed_kmh=float(speed_kmh),
                speed_source=speed_source,
                speed_validity=speed_validity,
            )
    return best


def _best_rpm_observation(
    *,
    t_s: float,
    samples: Sequence[Sample],
    metadata: RunMetadata,
    tire_circumference_m: float | None,
) -> _RpmObservation | None:
    best: _RpmObservation | None = None
    best_key: tuple[int, str, str] | None = None
    for sample in samples:
        engine_rpm, engine_rpm_source = _effective_engine_rpm(
            sample=sample,
            context=metadata,
            tire_circumference_m=tire_circumference_m,
        )
        if engine_rpm is None or not isfinite(engine_rpm) or engine_rpm <= 0.0:
            continue
        rpm_validity = _rpm_validity_for_source(engine_rpm_source)
        if rpm_validity == "missing":
            continue
        key = (
            _RPM_VALIDITY_RANK[rpm_validity],
            engine_rpm_source,
            str(sample.client_id),
        )
        if best_key is None or key > best_key:
            best_key = key
            best = _RpmObservation(
                t_s=t_s,
                engine_rpm=float(engine_rpm),
                engine_rpm_source=engine_rpm_source,
                rpm_validity=rpm_validity,
            )
    return best


def _nearest_observation_index(
    *,
    target_t_s: float,
    observation_times: Sequence[float],
) -> int | None:
    if not observation_times:
        return None
    index = bisect_left(observation_times, target_t_s)
    candidates: list[int] = []
    if index < len(observation_times):
        candidates.append(index)
    if index > 0:
        candidates.append(index - 1)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda candidate_index: (
            abs(observation_times[candidate_index] - target_t_s),
            observation_times[candidate_index],
        ),
    )


def _context_coverage(
    *,
    speed_validity: WholeRunSpeedValidity,
    speed_is_stale: bool,
    rpm_validity: WholeRunRpmValidity,
    rpm_is_stale: bool,
) -> WholeRunContextCoverage:
    fresh_speed = speed_validity != "missing" and not speed_is_stale
    fresh_rpm = rpm_validity != "missing" and not rpm_is_stale
    if fresh_speed and fresh_rpm:
        return "full"
    if speed_validity != "missing" or rpm_validity != "missing":
        return "partial"
    return "missing"


def _baseline_phase_state(
    *,
    speed_kmh: float | None,
    speed_validity: WholeRunSpeedValidity,
    speed_is_stale: bool,
) -> tuple[DrivingPhase, WholeRunContextLoadState]:
    if (
        speed_validity != "missing"
        and not speed_is_stale
        and speed_kmh is not None
        and speed_kmh < 3.0
    ):
        return DrivingPhase.IDLE, "idle"
    return DrivingPhase.SPEED_UNKNOWN, "unknown"


def _speed_validity_for_source(source: str) -> WholeRunSpeedValidity:
    if source.endswith("_unaligned"):
        return "missing"
    if source in {"gps", "obd2"}:
        return "measured"
    if source in {"manual", "fallback_manual"}:
        return "assumed"
    return "missing"


def _rpm_validity_for_source(source: str) -> WholeRunRpmValidity:
    if source == "context_unaligned":
        return "missing"
    if source == "estimated_from_speed_and_ratios":
        return "estimated"
    if source == "missing":
        return "missing"
    return "measured"


def _speed_source_rank(source: str) -> int:
    if source in {"gps", "obd2"}:
        return 2
    if source == "manual":
        return 1
    if source == "fallback_manual":
        return 0
    return 0


def _speed_source_requires_stale_context(source: str | None) -> bool:
    return source == "fallback_manual"
