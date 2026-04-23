"""Whole-run candidate-level spatial coherence over aligned multi-sensor windows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from vibesensor.shared.json_utils import safe_json_dumps, safe_json_loads
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.json_types import is_json_object
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunContextWindowLabel,
)
from vibesensor.use_cases.diagnostics._types import Sample
from vibesensor.use_cases.diagnostics.orders.matching import (
    best_order_peak_match,
    filtered_peak_pairs,
    order_peak_tolerance_hz,
)
from vibesensor.use_cases.diagnostics.orders.physics import _order_hypotheses
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import OrderTracePoint
from vibesensor.use_cases.diagnostics.orders.whole_run_traces import (
    WholeRunOrderTraceArtifactBundle,
)
from vibesensor.use_cases.diagnostics.spatial_evidence_contracts import (
    SpatialEvidenceSummary,
    SpatialEvidenceWindow,
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
    artifact = WholeRunArtifactFile(
        artifact_key=WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY,
        relative_path=_WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_PATH,
        file_format="jsonl",
        record_count=len(windows),
    )
    manifest = WholeRunArtifactManifest(
        run_id=order_trace_bundle.manifest.run_id,
        relative_dir=order_trace_bundle.manifest.relative_dir,
        window_policy=order_trace_bundle.manifest.window_policy,
        total_window_count=order_trace_bundle.manifest.total_window_count,
        artifacts=(artifact,),
        created_at=created_at or order_trace_bundle.manifest.created_at or utc_now_iso(),
        schema_version=order_trace_bundle.manifest.schema_version,
        storage_type=order_trace_bundle.manifest.storage_type,
    )
    return WholeRunSpatialCoherenceArtifactBundle(
        manifest=manifest,
        artifact_contents={
            WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY: (
                whole_run_spatial_evidence_windows_to_jsonl_bytes(windows)
            )
        },
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
    path_compliance_by_key = {
        hypothesis.key: hypothesis.path_compliance for hypothesis in _order_hypotheses()
    }
    points_by_candidate: dict[str, list[OrderTracePoint]] = defaultdict(list)
    for point in order_points:
        if point.eligible and point.predicted_hz is not None and point.predicted_hz > 0:
            points_by_candidate[point.hypothesis_key].append(point)
    candidate_rows: list[SpatialEvidenceWindow] = []
    for candidate_key in _ordered_candidate_keys(points_by_candidate):
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
    for candidate_key in _ordered_candidate_keys(rows_by_candidate):
        candidate_rows = sorted(
            rows_by_candidate[candidate_key],
            key=lambda row: (row.window_index, row.sensor_id),
        )
        windows_by_index: dict[int, list[SpatialEvidenceWindow]] = defaultdict(list)
        for row in candidate_rows:
            windows_by_index[row.window_index].append(row)
        coherence_scores = [
            max((row.coherence_score or 0.0) for row in window_rows if row.supporting)
            for window_rows in windows_by_index.values()
            if any(row.supporting for row in window_rows)
        ]
        summaries.append(
            SpatialEvidenceSummary(
                candidate_key=candidate_key,
                suspected_source=source_by_candidate[candidate_key],
                proof_basis="supporting_windows_raw_backed",
                total_window_count=len(windows_by_index),
                supporting_window_count=len(coherence_scores),
                supporting_sensor_count=len(
                    {row.sensor_id for row in candidate_rows if row.supporting}
                ),
                coherent_window_count=sum(1 for score in coherence_scores if score > 0.0),
                coherence_ratio=(
                    sum(coherence_scores) / len(coherence_scores) if coherence_scores else 0.0
                ),
            )
        )
    return tuple(summaries)


def whole_run_spatial_evidence_windows_to_jsonl_bytes(
    windows: Sequence[SpatialEvidenceWindow],
) -> bytes:
    """Serialize dense whole-run spatial evidence rows into sidecar JSONL bytes."""

    if not windows:
        return b""
    lines = [safe_json_dumps(window.to_json_object()).encode("utf-8") for window in windows]
    return b"\n".join(lines) + b"\n"


def whole_run_spatial_evidence_windows_from_jsonl_bytes(
    payload: bytes,
) -> tuple[SpatialEvidenceWindow, ...]:
    """Reconstruct persisted dense whole-run spatial evidence rows from JSONL bytes."""

    if not payload:
        return ()
    windows: list[SpatialEvidenceWindow] = []
    for raw_line in payload.decode("utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parsed = safe_json_loads(line, context="whole-run spatial evidence windows")
        if not is_json_object(parsed):
            raise ValueError("whole-run spatial evidence line must decode to a JSON object")
        windows.append(SpatialEvidenceWindow.from_mapping(parsed))
    return tuple(windows)


def _candidate_window_rows(
    *,
    point: OrderTracePoint,
    alignment_window: AlignedSpatialWindow,
    path_compliance: float,
) -> tuple[SpatialEvidenceWindow, ...]:
    support_by_sensor: dict[str, _CandidateSensorSupport] = {}
    for sensor_window in alignment_window.sensor_windows:
        if sensor_window.coverage_state != "full" or point.predicted_hz is None:
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


def _ordered_candidate_keys(rows_by_candidate: Mapping[str, object]) -> tuple[str, ...]:
    catalog_order = {hypothesis.key: index for index, hypothesis in enumerate(_order_hypotheses())}
    return tuple(
        sorted(
            rows_by_candidate,
            key=lambda candidate_key: (
                catalog_order.get(candidate_key, len(catalog_order)),
                candidate_key,
            ),
        )
    )


def _peak_intensity_db(peak: Mapping[str, object]) -> float | None:
    value = peak.get("vibration_strength_db")
    return float(value) if isinstance(value, (int, float)) else None
