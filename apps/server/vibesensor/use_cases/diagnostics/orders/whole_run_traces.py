"""Whole-run order-trace generation over spectral summaries and context labels."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.shared.types.whole_run_analysis import WholeRunArtifactManifest
from vibesensor.shared.window_quality import WindowQuality, window_quality_with_context
from vibesensor.use_cases.diagnostics._artifact_bundles import (
    build_single_artifact_bundle_parts,
)
from vibesensor.use_cases.diagnostics._jsonl_sidecars import jsonl_bytes_from_objects
from vibesensor.use_cases.diagnostics._reference_resolution import _tire_reference_from_context
from vibesensor.use_cases.diagnostics._sensor_locations import (
    client_locations_by_sensor,
    fallback_location_label,
)
from vibesensor.use_cases.diagnostics.orders.matching import (
    best_order_peak_match,
    filtered_peak_pairs,
)
from vibesensor.use_cases.diagnostics.orders.physics import (
    OrderHypothesis,
    _order_hypotheses,
    _order_label,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import (
    OrderTraceFamily,
    OrderTracePoint,
)
from vibesensor.use_cases.diagnostics.whole_run_context import WholeRunContextWindowLabel
from vibesensor.use_cases.diagnostics.whole_run_spectra import (
    WholeRunWindowSpectralSummary,
    whole_run_spectral_summaries_by_sensor,
)

WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY = "order-trace-points"
_WHOLE_RUN_ORDER_TRACE_ARTIFACT_PATH = "orders/trace-points.jsonl"

__all__ = [
    "WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY",
    "WholeRunOrderTraceArtifactBundle",
    "build_whole_run_order_trace_artifact_bundle",
    "order_trace_points_to_jsonl_bytes",
]


@dataclass(frozen=True, slots=True)
class WholeRunOrderTraceArtifactBundle:
    """Dense whole-run order-trace sidecar payload plus in-memory points."""

    manifest: WholeRunArtifactManifest
    artifact_contents: dict[str, bytes]
    points: tuple[OrderTracePoint, ...]


@dataclass(frozen=True, slots=True)
class _SensorPeakMatch:
    client_id: str
    location: str
    matched_hz: float
    amplitude_g: float
    relative_error: float
    peak_intensity_db: float | None
    vibration_strength_db: float | None
    window_quality: WindowQuality


def build_whole_run_order_trace_artifact_bundle(
    *,
    run_id: str,
    metadata: RunMetadata,
    spectral_manifest: WholeRunArtifactManifest,
    spectral_artifact_contents: Mapping[str, bytes],
    context_labels: Sequence[WholeRunContextWindowLabel],
    samples: Sequence[SensorFrame],
    lang: str = "en",
    created_at: str | None = None,
) -> WholeRunOrderTraceArtifactBundle:
    """Build deterministic dense whole-run order traces from persisted sidecars."""

    ordered_labels = tuple(sorted(context_labels, key=lambda label: label.window_index))
    if len(ordered_labels) != spectral_manifest.total_window_count:
        raise ValueError("whole-run order traces require context labels for every window")
    if any(label.window_index != index for index, label in enumerate(ordered_labels)):
        raise ValueError("whole-run order traces require contiguous ordered context labels")
    summaries_by_sensor = _spectral_summaries_by_sensor(
        manifest=spectral_manifest,
        artifact_contents=spectral_artifact_contents,
    )
    tire_circumference_m, _ = _tire_reference_from_context(metadata)
    client_locations = client_locations_by_sensor(samples, lang=lang)
    window_inputs = tuple(
        _window_context_sample(
            run_id=run_id,
            window_index=label.window_index,
            label=label,
            sample_rate_hz=spectral_manifest.window_policy.sample_rate_hz,
        )
        for label in ordered_labels
    )
    points: list[OrderTracePoint] = []
    for hypothesis in _order_hypotheses():
        hypothesis_points = _hypothesis_trace_points(
            hypothesis=hypothesis,
            metadata=metadata,
            tire_circumference_m=tire_circumference_m,
            window_inputs=window_inputs,
            context_labels=ordered_labels,
            summaries_by_sensor=summaries_by_sensor,
            client_locations=client_locations,
        )
        if any(point.eligible for point in hypothesis_points):
            points.extend(hypothesis_points)
    point_rows = tuple(points)
    parts = build_single_artifact_bundle_parts(
        artifact_key=WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY,
        relative_path=_WHOLE_RUN_ORDER_TRACE_ARTIFACT_PATH,
        file_format="jsonl",
        record_count=len(point_rows),
        source_manifest=spectral_manifest,
        run_id=run_id,
        created_at=created_at or spectral_manifest.created_at or utc_now_iso(),
        content_bytes=order_trace_points_to_jsonl_bytes(point_rows),
    )
    return WholeRunOrderTraceArtifactBundle(
        manifest=parts.manifest,
        artifact_contents=parts.artifact_contents,
        points=point_rows,
    )


def order_trace_points_to_jsonl_bytes(points: Sequence[OrderTracePoint]) -> bytes:
    """Serialize dense whole-run order traces into sidecar JSONL bytes."""

    return jsonl_bytes_from_objects(points)


def _hypothesis_trace_points(
    *,
    hypothesis: OrderHypothesis,
    metadata: RunMetadata,
    tire_circumference_m: float | None,
    window_inputs: Sequence[SensorFrame],
    context_labels: Sequence[WholeRunContextWindowLabel],
    summaries_by_sensor: Mapping[str, Sequence[WholeRunWindowSpectralSummary]],
    client_locations: Mapping[str, str],
) -> tuple[OrderTracePoint, ...]:
    family = cast(OrderTraceFamily, hypothesis.order_label_base)
    order_label = _order_label(hypothesis.order, hypothesis.order_label_base)
    points: list[OrderTracePoint] = []
    for sample, label in zip(window_inputs, context_labels, strict=True):
        predicted_hz, ref_source = hypothesis.predicted_hz(sample, metadata, tire_circumference_m)
        eligible = predicted_hz is not None and predicted_hz > 0
        sensor_match = (
            _best_sensor_peak_match(
                summaries_by_sensor=summaries_by_sensor,
                window_index=label.window_index,
                predicted_hz=float(predicted_hz),
                hypothesis=hypothesis,
                client_locations=client_locations,
                context_label=label,
            )
            if eligible and predicted_hz is not None
            else None
        )
        points.append(
            OrderTracePoint(
                hypothesis_key=hypothesis.key,
                suspected_source=str(hypothesis.suspected_source),
                order_family=family,
                harmonic=hypothesis.order,
                order_label=order_label,
                window_index=label.window_index,
                eligible=eligible,
                matched=sensor_match is not None,
                predicted_hz=float(predicted_hz) if predicted_hz is not None else None,
                matched_hz=sensor_match.matched_hz if sensor_match is not None else None,
                relative_error=sensor_match.relative_error if sensor_match is not None else None,
                peak_intensity_db=(
                    sensor_match.peak_intensity_db if sensor_match is not None else None
                ),
                vibration_strength_db=(
                    sensor_match.vibration_strength_db if sensor_match is not None else None
                ),
                ref_source=ref_source or None,
                strongest_location=(sensor_match.location if sensor_match is not None else None),
                window_quality_score=(
                    sensor_match.window_quality.score if sensor_match is not None else None
                ),
                window_quality_state=(
                    sensor_match.window_quality.state if sensor_match is not None else None
                ),
                window_quality_reasons=(
                    sensor_match.window_quality.reasons if sensor_match is not None else ()
                ),
            )
        )
    return tuple(points)


def _best_sensor_peak_match(
    *,
    summaries_by_sensor: Mapping[str, Sequence[WholeRunWindowSpectralSummary]],
    window_index: int,
    predicted_hz: float,
    hypothesis: OrderHypothesis,
    client_locations: Mapping[str, str],
    context_label: WholeRunContextWindowLabel,
) -> _SensorPeakMatch | None:
    best: _SensorPeakMatch | None = None
    for client_id in sorted(summaries_by_sensor):
        summaries = summaries_by_sensor[client_id]
        if window_index < 0 or window_index >= len(summaries):
            continue
        summary = summaries[window_index]
        if summary.coverage_state != "full":
            continue
        window_quality = window_quality_with_context(
            summary.window_quality,
            context_coverage=context_label.context_coverage,
            speed_validity=context_label.speed_validity,
            rpm_validity=context_label.rpm_validity,
        )
        if window_quality.state == "excluded":
            continue
        peak_index, peak_pairs = filtered_peak_pairs(summary.top_peaks)
        peak_match = best_order_peak_match(
            peak_pairs,
            predicted_hz=predicted_hz,
            path_compliance=hypothesis.path_compliance,
        )
        if peak_match is None:
            continue
        source_peak = summary.top_peaks[peak_index[peak_match.peak_index]]
        candidate = _SensorPeakMatch(
            client_id=client_id,
            location=client_locations.get(client_id, fallback_location_label(client_id)),
            matched_hz=peak_match.matched_hz,
            amplitude_g=peak_match.amplitude_g,
            relative_error=peak_match.relative_error,
            peak_intensity_db=source_peak.get("vibration_strength_db"),
            vibration_strength_db=summary.vibration_strength_db,
            window_quality=window_quality,
        )
        if best is None or _sensor_match_rank(candidate) > _sensor_match_rank(best):
            best = candidate
    return best


def _spectral_summaries_by_sensor(
    *,
    manifest: WholeRunArtifactManifest,
    artifact_contents: Mapping[str, bytes],
) -> dict[str, tuple[WholeRunWindowSpectralSummary, ...]]:
    summaries_by_sensor = whole_run_spectral_summaries_by_sensor(
        manifest=manifest,
        artifact_contents=artifact_contents,
    )
    if not summaries_by_sensor:
        raise ValueError("whole-run order traces require at least one spectral summary artifact")
    return summaries_by_sensor


def _window_context_sample(
    *,
    run_id: str,
    window_index: int,
    label: WholeRunContextWindowLabel,
    sample_rate_hz: int,
) -> SensorFrame:
    return SensorFrame(
        run_id=run_id,
        timestamp_utc=f"whole-run-window-{window_index}",
        t_s=None,
        client_id="",
        client_name="",
        location="",
        sample_rate_hz=sample_rate_hz,
        speed_kmh=label.speed_kmh,
        gps_speed_kmh=label.speed_kmh if label.speed_source == "gps" else None,
        speed_source=label.speed_source or "",
        engine_rpm=label.engine_rpm,
        engine_rpm_source=label.engine_rpm_source or "",
        gear=None,
        final_drive_ratio=None,
        accel_x_g=None,
        accel_y_g=None,
        accel_z_g=None,
        dominant_freq_hz=None,
        dominant_axis="",
        top_peaks=(),
        vibration_strength_db=None,
        strength_bucket=None,
        strength_peak_amp_g=None,
        strength_floor_amp_g=None,
        frames_dropped_total=0,
        queue_overflow_drops=0,
    )


def _sensor_match_rank(match: _SensorPeakMatch) -> tuple[float, float, str]:
    return (match.amplitude_g, -match.relative_error, match.client_id)
