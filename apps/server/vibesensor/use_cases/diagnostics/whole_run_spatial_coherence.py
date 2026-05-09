"""Whole-run candidate-level spatial coherence over aligned multi-sensor windows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from vibesensor.domain import LocationHotspot
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactManifest,
    WholeRunContextWindowLabel,
)
from vibesensor.use_cases.diagnostics._artifact_bundles import (
    build_single_artifact_bundle_parts,
)
from vibesensor.use_cases.diagnostics._jsonl_sidecars import (
    jsonl_bytes_from_objects,
    jsonl_objects_from_bytes,
)
from vibesensor.use_cases.diagnostics._ranking_utils import sortable_optional_metric
from vibesensor.use_cases.diagnostics._types import Sample
from vibesensor.use_cases.diagnostics.location_scoring import (
    NEAR_TIE_DOMINANCE_THRESHOLD,
)
from vibesensor.use_cases.diagnostics.math_utils import (
    _max_or_none,
    _mean_or_none,
    _ratio_or_zero,
)
from vibesensor.use_cases.diagnostics.orders._hypothesis_catalog import (
    order_hypothesis_path_compliance_by_key,
    ordered_order_hypothesis_keys,
)
from vibesensor.use_cases.diagnostics.orders.matching import (
    best_order_peak_match,
    filtered_peak_pairs,
    order_peak_tolerance_hz,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import OrderTracePoint
from vibesensor.use_cases.diagnostics.orders.whole_run_traces import (
    WholeRunOrderTraceArtifactBundle,
)
from vibesensor.use_cases.diagnostics.spatial_evidence_contracts import (
    SpatialEvidenceSummary,
    SpatialEvidenceWindow,
    SpatialLocationSummary,
)
from vibesensor.use_cases.diagnostics.whole_run_spatial_alignment import (
    AlignedSpatialWindow,
    WholeRunSpatialAlignmentMatrix,
    build_whole_run_spatial_alignment_matrix,
)

WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY = "spatial-coherence-windows"
_WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_PATH = "spatial/coherence-windows.jsonl"

__all__ = [
    "WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY",
    "WholeRunSpatialCoherenceArtifactBundle",
    "build_whole_run_spatial_coherence_artifact_bundle",
    "build_whole_run_spatial_evidence_windows",
    "summarize_whole_run_spatial_coherence",
    "whole_run_spatial_evidence_windows_from_jsonl_bytes",
    "whole_run_spatial_evidence_windows_to_jsonl_bytes",
]


@dataclass(frozen=True, slots=True)
class WholeRunSpatialCoherenceArtifactBundle:
    """Dense per-candidate spatial evidence windows plus compact coherence summaries."""

    manifest: WholeRunArtifactManifest
    artifact_contents: dict[str, bytes]
    windows: tuple[SpatialEvidenceWindow, ...]
    summaries: tuple[SpatialEvidenceSummary, ...]


@dataclass(frozen=True, slots=True)
class _CandidateSensorSupport:
    sensor_id: str
    location: str
    matched_frequency_hz: float
    peak_intensity_db: float | None
    vibration_strength_db: float | None


def build_whole_run_spatial_coherence_artifact_bundle(
    *,
    order_trace_bundle: WholeRunOrderTraceArtifactBundle,
    spectral_manifest: WholeRunArtifactManifest,
    spectral_artifact_contents: Mapping[str, bytes],
    context_labels: Sequence[WholeRunContextWindowLabel],
    samples: Sequence[Sample],
    lang: str = "en",
    created_at: str | None = None,
) -> WholeRunSpatialCoherenceArtifactBundle:
    """Build dense candidate-level spatial coherence rows from aligned windows."""

    alignment_matrix = build_whole_run_spatial_alignment_matrix(
        spectral_manifest=spectral_manifest,
        spectral_artifact_contents=spectral_artifact_contents,
        context_labels=context_labels,
        samples=samples,
        lang=lang,
    )
    windows = build_whole_run_spatial_evidence_windows(
        alignment_matrix=alignment_matrix,
        order_points=order_trace_bundle.points,
    )
    summaries = summarize_whole_run_spatial_coherence(windows)
    parts = build_single_artifact_bundle_parts(
        artifact_key=WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY,
        relative_path=_WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_PATH,
        file_format="jsonl",
        record_count=len(windows),
        source_manifest=order_trace_bundle.manifest,
        created_at=created_at or order_trace_bundle.manifest.created_at or utc_now_iso(),
        content_bytes=whole_run_spatial_evidence_windows_to_jsonl_bytes(windows),
    )
    return WholeRunSpatialCoherenceArtifactBundle(
        manifest=parts.manifest,
        artifact_contents=parts.artifact_contents,
        windows=windows,
        summaries=summaries,
    )


def build_whole_run_spatial_evidence_windows(
    *,
    alignment_matrix: WholeRunSpatialAlignmentMatrix,
    order_points: Sequence[OrderTracePoint],
) -> tuple[SpatialEvidenceWindow, ...]:
    """Join order candidates against aligned sensor windows into dense spatial rows."""

    windows_by_index = {window.window_index: window for window in alignment_matrix.windows}
    path_compliance_by_key = order_hypothesis_path_compliance_by_key()
    points_by_candidate: dict[str, list[OrderTracePoint]] = defaultdict(list)
    for point in order_points:
        if point.eligible and point.predicted_hz is not None and point.predicted_hz > 0:
            points_by_candidate[point.hypothesis_key].append(point)
    candidate_rows: list[SpatialEvidenceWindow] = []
    for candidate_key in ordered_order_hypothesis_keys(points_by_candidate):
        candidate_points = sorted(
            points_by_candidate[candidate_key],
            key=lambda point: point.window_index,
        )
        path_compliance = path_compliance_by_key.get(candidate_key, 1.0)
        for point in candidate_points:
            alignment_window = windows_by_index.get(point.window_index)
            if alignment_window is None:
                raise ValueError(
                    "whole-run spatial coherence requires aligned sensor rows for every "
                    f"candidate window, missing {point.window_index}"
                )
            candidate_rows.extend(
                _candidate_window_rows(
                    point=point,
                    alignment_window=alignment_window,
                    path_compliance=path_compliance,
                )
            )
    return tuple(candidate_rows)


def summarize_whole_run_spatial_coherence(
    windows: Sequence[SpatialEvidenceWindow],
) -> tuple[SpatialEvidenceSummary, ...]:
    """Collapse dense candidate-level rows into compact coherence summaries."""

    rows_by_candidate: dict[str, list[SpatialEvidenceWindow]] = defaultdict(list)
    source_by_candidate: dict[str, str] = {}
    for row in windows:
        rows_by_candidate[row.candidate_key].append(row)
        source_by_candidate.setdefault(row.candidate_key, row.suspected_source)
    summaries: list[SpatialEvidenceSummary] = []
    for candidate_key in ordered_order_hypothesis_keys(rows_by_candidate):
        candidate_rows = sorted(
            rows_by_candidate[candidate_key],
            key=lambda row: (row.window_index, row.sensor_id),
        )
        windows_by_index: dict[int, list[SpatialEvidenceWindow]] = defaultdict(list)
        for row in candidate_rows:
            windows_by_index[row.window_index].append(row)
        supporting_window_count = sum(
            1
            for window_rows in windows_by_index.values()
            if any(row.supporting for row in window_rows)
        )
        coherent_window_count = sum(
            1
            for window_rows in windows_by_index.values()
            if any(row.coherent for row in window_rows)
        )
        location_summaries = _summarize_location_support(
            candidate_rows,
            supporting_window_count=supporting_window_count,
        )
        dominant_location = location_summaries[0].location if location_summaries else None
        runner_up_location = location_summaries[1].location if len(location_summaries) > 1 else None
        dominance_ratio = _location_dominance_ratio(location_summaries)
        weak_spatial_separation = _weak_spatial_separation(
            location_summaries,
            dominance_ratio=dominance_ratio,
        )
        summaries.append(
            SpatialEvidenceSummary(
                candidate_key=candidate_key,
                suspected_source=source_by_candidate[candidate_key],
                proof_basis="supporting_windows_raw_backed",
                total_window_count=len(windows_by_index),
                supporting_window_count=supporting_window_count,
                supporting_sensor_count=len(
                    {row.sensor_id for row in candidate_rows if row.supporting}
                ),
                coherent_window_count=coherent_window_count,
                coherence_ratio=_ratio_or_zero(
                    coherent_window_count,
                    supporting_window_count,
                ),
                dominant_location=dominant_location,
                runner_up_location=runner_up_location,
                location_separation_db=_location_separation_db(location_summaries),
                dominance_ratio=dominance_ratio,
                ambiguous_location=_ambiguous_location(
                    location_summaries,
                    dominance_ratio=dominance_ratio,
                ),
                weak_spatial_separation=weak_spatial_separation,
                location_summaries=location_summaries,
            )
        )
    return tuple(summaries)


def whole_run_spatial_evidence_windows_to_jsonl_bytes(
    windows: Sequence[SpatialEvidenceWindow],
) -> bytes:
    """Serialize dense whole-run spatial evidence rows into sidecar JSONL bytes."""

    return jsonl_bytes_from_objects(windows)


def whole_run_spatial_evidence_windows_from_jsonl_bytes(
    payload: bytes,
) -> tuple[SpatialEvidenceWindow, ...]:
    """Reconstruct persisted dense whole-run spatial evidence rows from JSONL bytes."""

    return jsonl_objects_from_bytes(
        payload,
        context="whole-run spatial evidence windows",
        line_description="whole-run spatial evidence line",
        from_mapping=SpatialEvidenceWindow.from_mapping,
    )


def _candidate_window_rows(
    *,
    point: OrderTracePoint,
    alignment_window: AlignedSpatialWindow,
    path_compliance: float,
) -> tuple[SpatialEvidenceWindow, ...]:
    support_by_sensor: dict[str, _CandidateSensorSupport] = {}
    for sensor_window in alignment_window.sensor_windows:
        if (
            sensor_window.coverage_state != "full"
            or sensor_window.window_quality.state == "excluded"
            or point.predicted_hz is None
        ):
            continue
        peak_indexes, peak_pairs = filtered_peak_pairs(sensor_window.top_peaks)
        peak_match = best_order_peak_match(
            peak_pairs,
            predicted_hz=point.predicted_hz,
            path_compliance=path_compliance,
        )
        if peak_match is None:
            continue
        source_peak = sensor_window.top_peaks[peak_indexes[peak_match.peak_index]]
        support_by_sensor[sensor_window.sensor_id] = _CandidateSensorSupport(
            sensor_id=sensor_window.sensor_id,
            location=sensor_window.location,
            matched_frequency_hz=peak_match.matched_hz,
            peak_intensity_db=_peak_intensity_db(source_peak),
            vibration_strength_db=sensor_window.vibration_strength_db,
        )
    window_coherence_score = _window_coherence_score(
        predicted_hz=point.predicted_hz,
        path_compliance=path_compliance,
        full_sensor_count=alignment_window.full_sensor_count,
        supporting_matches=tuple(support_by_sensor.values()),
    )
    coherent_sensor_ids = set(support_by_sensor) if window_coherence_score > 0.0 else set()
    rows: list[SpatialEvidenceWindow] = []
    for sensor_window in alignment_window.sensor_windows:
        sensor_support = support_by_sensor.get(sensor_window.sensor_id)
        rows.append(
            SpatialEvidenceWindow(
                candidate_key=point.hypothesis_key,
                suspected_source=point.suspected_source,
                window_index=alignment_window.window_index,
                sensor_id=sensor_window.sensor_id,
                location=sensor_window.location,
                supporting=sensor_support is not None,
                coherent=sensor_window.sensor_id in coherent_sensor_ids,
                peak_intensity_db=(
                    sensor_support.peak_intensity_db if sensor_support is not None else None
                ),
                vibration_strength_db=(
                    sensor_support.vibration_strength_db
                    if sensor_support is not None
                    else sensor_window.vibration_strength_db
                ),
                matched_frequency_hz=(
                    sensor_support.matched_frequency_hz if sensor_support is not None else None
                ),
                coherence_score=(window_coherence_score if sensor_support is not None else None),
            )
        )
    return tuple(rows)


def _window_coherence_score(
    *,
    predicted_hz: float | None,
    path_compliance: float,
    full_sensor_count: int,
    supporting_matches: Sequence[_CandidateSensorSupport],
) -> float:
    if (
        predicted_hz is None
        or predicted_hz <= 0.0
        or full_sensor_count < 2
        or len(supporting_matches) < 2
    ):
        return 0.0
    tolerance_hz = order_peak_tolerance_hz(
        predicted_hz=predicted_hz,
        path_compliance=path_compliance,
    )
    matched_hz = sorted(match.matched_frequency_hz for match in supporting_matches)
    spread_hz = matched_hz[-1] - matched_hz[0]
    if spread_hz > tolerance_hz:
        return 0.0
    coverage_ratio = len(supporting_matches) / max(1, full_sensor_count)
    spread_score = max(0.0, 1.0 - (spread_hz / max(1e-9, tolerance_hz)))
    return max(0.0, min(1.0, coverage_ratio * spread_score))


def _peak_intensity_db(peak: Mapping[str, object]) -> float | None:
    value = peak.get("vibration_strength_db")
    return float(value) if isinstance(value, (int, float)) else None


def _summarize_location_support(
    candidate_rows: Sequence[SpatialEvidenceWindow],
    *,
    supporting_window_count: int,
) -> tuple[SpatialLocationSummary, ...]:
    rows_by_location: dict[str, list[SpatialEvidenceWindow]] = defaultdict(list)
    for row in candidate_rows:
        if row.supporting:
            rows_by_location[row.location].append(row)
    summaries = [
        _build_location_summary(
            location,
            rows,
            supporting_window_count=supporting_window_count,
        )
        for location, rows in rows_by_location.items()
    ]
    return tuple(
        sorted(
            summaries,
            key=lambda summary: (
                -summary.support_ratio,
                -summary.coherent_window_count,
                -(summary.coherence_ratio or 0.0),
                -sortable_optional_metric(summary.mean_vibration_strength_db),
                -sortable_optional_metric(summary.peak_intensity_db),
                summary.location.lower(),
            ),
        )
    )


def _build_location_summary(
    location: str,
    rows: Sequence[SpatialEvidenceWindow],
    *,
    supporting_window_count: int,
) -> SpatialLocationSummary:
    support_windows = {row.window_index for row in rows}
    coherent_windows = {row.window_index for row in rows if row.coherent}
    vibration_strengths = [
        row.vibration_strength_db for row in rows if row.vibration_strength_db is not None
    ]
    peak_intensities = [row.peak_intensity_db for row in rows if row.peak_intensity_db is not None]
    return SpatialLocationSummary(
        location=location,
        sensor_ids=tuple(sorted({row.sensor_id for row in rows})),
        supporting_window_count=len(support_windows),
        support_ratio=_ratio_or_zero(len(support_windows), supporting_window_count),
        coherent_window_count=len(coherent_windows),
        coherence_ratio=_ratio_or_zero(len(coherent_windows), len(support_windows)),
        peak_intensity_db=_max_or_none(peak_intensities),
        mean_vibration_strength_db=_mean_or_none(vibration_strengths),
    )


def _location_dominance_ratio(
    location_summaries: Sequence[SpatialLocationSummary],
) -> float | None:
    if len(location_summaries) < 2:
        return None
    top_support = location_summaries[0].support_ratio
    runner_up_support = location_summaries[1].support_ratio
    if runner_up_support <= 0.0:
        return None
    return top_support / runner_up_support


def _location_separation_db(
    location_summaries: Sequence[SpatialLocationSummary],
) -> float | None:
    if len(location_summaries) < 2:
        return None
    top = _location_reference_db(location_summaries[0])
    runner_up = _location_reference_db(location_summaries[1])
    if top is None or runner_up is None:
        return None
    return top - runner_up


def _location_reference_db(summary: SpatialLocationSummary) -> float | None:
    if summary.mean_vibration_strength_db is not None:
        return summary.mean_vibration_strength_db
    return summary.peak_intensity_db


def _ambiguous_location(
    location_summaries: Sequence[SpatialLocationSummary],
    *,
    dominance_ratio: float | None,
) -> bool:
    return (
        len(location_summaries) > 1
        and dominance_ratio is not None
        and dominance_ratio < NEAR_TIE_DOMINANCE_THRESHOLD
    )


def _weak_spatial_separation(
    location_summaries: Sequence[SpatialLocationSummary],
    *,
    dominance_ratio: float | None,
) -> bool:
    if not location_summaries:
        return True
    if len(location_summaries) < 2 or dominance_ratio is None:
        return False
    threshold = LocationHotspot.weak_spatial_threshold(len(location_summaries))
    return dominance_ratio < threshold
