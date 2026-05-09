"""Coverage and sidecar projection helpers for whole-run spectral artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, cast

from vibesensor.shared.json_utils import i18n_ref
from vibesensor.shared.raw_capture_timeline import (
    RawSensorTimeline,
    raw_timeline_has_unverified_sync,
    raw_timeline_is_legacy,
)
from vibesensor.shared.run_context_warning import (
    WARNING_CODE_WHOLE_RUN_ALIGNMENT_INCOMPLETE,
    RunContextWarning,
)
from vibesensor.shared.types.json_types import JsonObject, is_json_object
from vibesensor.shared.types.raw_capture import (
    RawCaptureCoverageState,
    RawCaptureSensorData,
    RawRunCapture,
)
from vibesensor.shared.types.whole_run_analysis import WholeRunArtifactManifest
from vibesensor.shared.window_quality import WindowQuality, clean_window_quality
from vibesensor.use_cases.diagnostics._jsonl_sidecars import (
    jsonl_bytes_from_objects,
    jsonl_objects_from_bytes,
)
from vibesensor.use_cases.diagnostics.whole_run_windows import WholeRunWindowPlan
from vibesensor.vibration_strength import StrengthPeak

type WholeRunCoverageConfidence = Literal["full", "partial", "unavailable"]


@dataclass(frozen=True, slots=True)
class WholeRunWindowSpectralSummary:
    """Compact per-window spectral facts persisted alongside dense spectrum matrices."""

    window_index: int
    coverage_state: RawCaptureCoverageState
    returned_sample_start: int | None
    returned_sample_count: int
    window_start_t_s: float | None = None
    window_end_t_s: float | None = None
    coverage_reason: str | None = None
    dominant_freq_hz: float | None = None
    vibration_strength_db: float | None = None
    strength_peak_amp_g: float | None = None
    strength_floor_amp_g: float | None = None
    strength_bucket: str | None = None
    top_peaks: tuple[StrengthPeak, ...] = ()
    window_quality: WindowQuality = field(default_factory=clean_window_quality)

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "window_index": self.window_index,
            "coverage_state": self.coverage_state,
            "returned_sample_start": self.returned_sample_start,
            "returned_sample_count": self.returned_sample_count,
        }
        if self.window_start_t_s is not None:
            payload["window_start_t_s"] = self.window_start_t_s
        if self.window_end_t_s is not None:
            payload["window_end_t_s"] = self.window_end_t_s
        if self.coverage_reason is not None:
            payload["coverage_reason"] = self.coverage_reason
        payload["top_peaks"] = [
            {
                "hz": float(peak["hz"]),
                "amp": float(peak["amp"]),
                "vibration_strength_db": float(peak["vibration_strength_db"]),
                "strength_bucket": peak["strength_bucket"],
            }
            for peak in self.top_peaks
            if peak["hz"] > 0 and peak["amp"] > 0
        ]
        if self.dominant_freq_hz is not None:
            payload["dominant_freq_hz"] = self.dominant_freq_hz
        if self.vibration_strength_db is not None:
            payload["vibration_strength_db"] = self.vibration_strength_db
        if self.strength_peak_amp_g is not None:
            payload["strength_peak_amp_g"] = self.strength_peak_amp_g
        if self.strength_floor_amp_g is not None:
            payload["strength_floor_amp_g"] = self.strength_floor_amp_g
        if self.strength_bucket is not None:
            payload["strength_bucket"] = self.strength_bucket
        payload["window_quality"] = self.window_quality.to_json_object()
        return payload

    @classmethod
    def from_mapping(cls, data: JsonObject) -> WholeRunWindowSpectralSummary:
        top_peaks_raw = data.get("top_peaks")
        top_peaks: list[StrengthPeak] = []
        if isinstance(top_peaks_raw, list):
            for item in top_peaks_raw:
                if not is_json_object(item):
                    continue
                hz = _float_or_none(item.get("hz"))
                amp = _float_or_none(item.get("amp"))
                vibration_strength_db = _float_or_none(item.get("vibration_strength_db"))
                if hz is None or amp is None or vibration_strength_db is None:
                    continue
                top_peaks.append(
                    {
                        "hz": hz,
                        "amp": amp,
                        "vibration_strength_db": vibration_strength_db,
                        "strength_bucket": _text_or_none(item.get("strength_bucket")),
                    }
                )
        return cls(
            window_index=_int_or_default(data.get("window_index"), default=0),
            coverage_state=_coverage_state(data.get("coverage_state")),
            returned_sample_start=_int_or_none(data.get("returned_sample_start")),
            returned_sample_count=_int_or_default(data.get("returned_sample_count"), default=0),
            window_start_t_s=_float_or_none(data.get("window_start_t_s")),
            window_end_t_s=_float_or_none(data.get("window_end_t_s")),
            coverage_reason=_text_or_none(data.get("coverage_reason")),
            dominant_freq_hz=_float_or_none(data.get("dominant_freq_hz")),
            vibration_strength_db=_float_or_none(data.get("vibration_strength_db")),
            strength_peak_amp_g=_float_or_none(data.get("strength_peak_amp_g")),
            strength_floor_amp_g=_float_or_none(data.get("strength_floor_amp_g")),
            strength_bucket=_text_or_none(data.get("strength_bucket")),
            top_peaks=tuple(top_peaks),
            window_quality=(
                WindowQuality.from_mapping(window_quality_raw)
                if is_json_object(window_quality_raw := data.get("window_quality"))
                else clean_window_quality()
            ),
        )


@dataclass(frozen=True, slots=True)
class WholeRunSpectralCoverageSummary:
    """Rolled-up coverage facts for time-aligned whole-run spectral windows."""

    total_sensor_window_count: int
    full_sensor_window_count: int
    partial_sensor_window_count: int
    missing_sensor_window_count: int
    empty_sensor_window_count: int
    gap_count: int
    overlap_count: int
    dropped_chunk_count: int
    late_packet_chunk_count: int
    queue_overflow_chunk_count: int
    invalid_chunk_count: int
    write_error_chunk_count: int
    sample_rate_mismatch_sensor_count: int
    sample_rate_unverified_sensor_count: int
    unanchored_sensor_count: int
    legacy_sensor_count: int
    sync_unverified_sensor_count: int
    stale_sync_sensor_count: int
    high_rtt_sensor_count: int
    coverage_confidence: WholeRunCoverageConfidence
    udp_ingest_queue_drop_count: int = 0
    usable_window_count: int = 0
    limited_window_count: int = 0
    excluded_window_count: int = 0
    mean_quality_score: float | None = None
    warnings: tuple[RunContextWarning, ...] = ()


def build_coverage_summary(
    *,
    raw_capture: RawRunCapture,
    plan: WholeRunWindowPlan | None,
    sensors: Sequence[RawCaptureSensorData],
    timelines: Mapping[str, RawSensorTimeline],
    summaries_by_sensor: Mapping[str, Sequence[WholeRunWindowSpectralSummary]],
) -> WholeRunSpectralCoverageSummary:
    total_sensor_window_count = 0
    full_sensor_window_count = 0
    partial_sensor_window_count = 0
    missing_sensor_window_count = 0
    empty_sensor_window_count = 0
    quality_scores: list[float] = []
    usable_window_count = 0
    limited_window_count = 0
    excluded_window_count = 0
    for sensor in sensors:
        summaries = summaries_by_sensor.get(sensor.manifest.client_id, ())
        if not summaries and plan is not None:
            total_sensor_window_count += plan.total_window_count
            missing_sensor_window_count += plan.total_window_count
            continue
        for summary in summaries:
            total_sensor_window_count += 1
            quality = summary.window_quality
            quality_scores.append(quality.score)
            if quality.state == "usable":
                usable_window_count += 1
            elif quality.state == "limited":
                limited_window_count += 1
            else:
                excluded_window_count += 1
            if summary.coverage_state == "full":
                full_sensor_window_count += 1
            elif summary.coverage_state == "partial":
                partial_sensor_window_count += 1
            elif summary.coverage_state == "empty":
                empty_sensor_window_count += 1
            else:
                missing_sensor_window_count += 1
    gap_count = sum(len(timeline.gap_intervals) for timeline in timelines.values())
    overlap_count = sum(len(timeline.overlap_intervals) for timeline in timelines.values())
    sample_rate_mismatch_sensor_count = sum(
        1
        for sensor in sensors
        if sensor.manifest.sample_rate_corrected
        or sensor.manifest.sample_rate_proof_state == "timing_inconsistent"
    )
    sample_rate_unverified_sensor_count = sum(
        1 for sensor in sensors if sensor.manifest.sample_rate_unverified
    )
    unanchored_sensor_count = sum(1 for timeline in timelines.values() if not timeline.anchored)
    legacy_sensor_count = sum(
        1 for timeline in timelines.values() if raw_timeline_is_legacy(timeline)
    )
    sync_unverified_sensor_count = sum(
        1 for timeline in timelines.values() if raw_timeline_has_unverified_sync(timeline)
    )
    stale_sync_sensor_count = sum(
        1
        for timeline in timelines.values()
        if timeline.clock_sync is not None and timeline.clock_sync.proof_state == "stale_sync"
    )
    high_rtt_sensor_count = sum(
        1
        for timeline in timelines.values()
        if timeline.clock_sync is not None and timeline.clock_sync.proof_state == "high_rtt"
    )
    dropped_chunk_count = raw_capture.manifest.total_dropped_chunk_count
    late_packet_chunk_count = raw_capture.manifest.total_late_packet_chunk_count
    udp_ingest_queue_drop_count = raw_capture.manifest.losses.udp_ingest_queue_drop_count
    queue_overflow_chunk_count = raw_capture.manifest.losses.queue_overflow_chunk_count
    invalid_chunk_count = raw_capture.manifest.losses.invalid_chunk_count
    write_error_chunk_count = raw_capture.manifest.losses.write_error_chunk_count
    coverage_confidence = build_coverage_confidence(
        total_sensor_window_count=total_sensor_window_count,
        partial_sensor_window_count=partial_sensor_window_count,
        missing_sensor_window_count=missing_sensor_window_count,
        empty_sensor_window_count=empty_sensor_window_count,
        gap_count=gap_count,
        overlap_count=overlap_count,
        dropped_chunk_count=dropped_chunk_count,
        late_packet_chunk_count=late_packet_chunk_count,
        sample_rate_mismatch_sensor_count=sample_rate_mismatch_sensor_count,
        sample_rate_unverified_sensor_count=sample_rate_unverified_sensor_count,
        unanchored_sensor_count=unanchored_sensor_count,
        sync_unverified_sensor_count=sync_unverified_sensor_count,
    )
    warnings = build_whole_run_warnings(
        total_sensor_window_count=total_sensor_window_count,
        partial_sensor_window_count=partial_sensor_window_count,
        missing_sensor_window_count=missing_sensor_window_count,
        empty_sensor_window_count=empty_sensor_window_count,
        gap_count=gap_count,
        overlap_count=overlap_count,
        dropped_chunk_count=dropped_chunk_count,
        late_packet_chunk_count=late_packet_chunk_count,
        udp_ingest_queue_drop_count=udp_ingest_queue_drop_count,
        queue_overflow_chunk_count=queue_overflow_chunk_count,
        invalid_chunk_count=invalid_chunk_count,
        write_error_chunk_count=write_error_chunk_count,
        sample_rate_mismatch_sensor_count=sample_rate_mismatch_sensor_count,
        sample_rate_unverified_sensor_count=sample_rate_unverified_sensor_count,
        legacy_sensor_count=legacy_sensor_count,
        unanchored_sensor_count=unanchored_sensor_count,
        sync_unverified_sensor_count=sync_unverified_sensor_count,
        stale_sync_sensor_count=stale_sync_sensor_count,
        high_rtt_sensor_count=high_rtt_sensor_count,
    )
    return WholeRunSpectralCoverageSummary(
        total_sensor_window_count=total_sensor_window_count,
        full_sensor_window_count=full_sensor_window_count,
        partial_sensor_window_count=partial_sensor_window_count,
        missing_sensor_window_count=missing_sensor_window_count,
        empty_sensor_window_count=empty_sensor_window_count,
        gap_count=gap_count,
        overlap_count=overlap_count,
        dropped_chunk_count=dropped_chunk_count,
        late_packet_chunk_count=late_packet_chunk_count,
        udp_ingest_queue_drop_count=udp_ingest_queue_drop_count,
        queue_overflow_chunk_count=queue_overflow_chunk_count,
        invalid_chunk_count=invalid_chunk_count,
        write_error_chunk_count=write_error_chunk_count,
        sample_rate_mismatch_sensor_count=sample_rate_mismatch_sensor_count,
        sample_rate_unverified_sensor_count=sample_rate_unverified_sensor_count,
        unanchored_sensor_count=unanchored_sensor_count,
        legacy_sensor_count=legacy_sensor_count,
        sync_unverified_sensor_count=sync_unverified_sensor_count,
        stale_sync_sensor_count=stale_sync_sensor_count,
        high_rtt_sensor_count=high_rtt_sensor_count,
        coverage_confidence=coverage_confidence,
        usable_window_count=usable_window_count,
        limited_window_count=limited_window_count,
        excluded_window_count=excluded_window_count,
        mean_quality_score=(sum(quality_scores) / len(quality_scores) if quality_scores else None),
        warnings=warnings,
    )


def build_coverage_confidence(
    *,
    total_sensor_window_count: int,
    partial_sensor_window_count: int,
    missing_sensor_window_count: int,
    empty_sensor_window_count: int,
    gap_count: int,
    overlap_count: int,
    dropped_chunk_count: int,
    late_packet_chunk_count: int,
    sample_rate_mismatch_sensor_count: int,
    sample_rate_unverified_sensor_count: int,
    unanchored_sensor_count: int,
    sync_unverified_sensor_count: int,
) -> WholeRunCoverageConfidence:
    if total_sensor_window_count <= 0:
        return "unavailable"
    if (
        partial_sensor_window_count <= 0
        and missing_sensor_window_count <= 0
        and empty_sensor_window_count <= 0
        and gap_count <= 0
        and overlap_count <= 0
        and dropped_chunk_count <= 0
        and late_packet_chunk_count <= 0
        and sample_rate_mismatch_sensor_count <= 0
        and sample_rate_unverified_sensor_count <= 0
        and unanchored_sensor_count <= 0
        and sync_unverified_sensor_count <= 0
    ):
        return "full"
    return "partial"


def build_whole_run_warnings(
    *,
    total_sensor_window_count: int,
    partial_sensor_window_count: int,
    missing_sensor_window_count: int,
    empty_sensor_window_count: int,
    gap_count: int,
    overlap_count: int,
    dropped_chunk_count: int,
    late_packet_chunk_count: int,
    udp_ingest_queue_drop_count: int,
    queue_overflow_chunk_count: int,
    invalid_chunk_count: int,
    write_error_chunk_count: int,
    sample_rate_mismatch_sensor_count: int,
    sample_rate_unverified_sensor_count: int,
    legacy_sensor_count: int,
    unanchored_sensor_count: int,
    sync_unverified_sensor_count: int,
    stale_sync_sensor_count: int,
    high_rtt_sensor_count: int,
) -> tuple[RunContextWarning, ...]:
    if (
        partial_sensor_window_count <= 0
        and missing_sensor_window_count <= 0
        and empty_sensor_window_count <= 0
        and gap_count <= 0
        and overlap_count <= 0
        and dropped_chunk_count <= 0
        and late_packet_chunk_count <= 0
        and sample_rate_mismatch_sensor_count <= 0
        and sample_rate_unverified_sensor_count <= 0
        and sync_unverified_sensor_count <= 0
        and unanchored_sensor_count <= 0
        and legacy_sensor_count <= 0
    ):
        return ()
    missing_sync_sensor_count = max(
        0,
        sync_unverified_sensor_count
        - max(0, stale_sync_sensor_count)
        - max(0, high_rtt_sensor_count),
    )
    detail_key = (
        "RUN_CONTEXT_WARNING_WHOLE_RUN_ALIGNMENT_UNAVAILABLE_DETAIL"
        if total_sensor_window_count <= 0
        else "RUN_CONTEXT_WARNING_WHOLE_RUN_ALIGNMENT_INCOMPLETE_DETAIL"
    )
    return (
        RunContextWarning(
            code=WARNING_CODE_WHOLE_RUN_ALIGNMENT_INCOMPLETE,
            severity="warn",
            applies_to="whole_run",
            title=i18n_ref("RUN_CONTEXT_WARNING_WHOLE_RUN_ALIGNMENT_INCOMPLETE_TITLE"),
            detail=i18n_ref(
                detail_key,
                partial=str(max(0, partial_sensor_window_count)),
                missing=str(max(0, missing_sensor_window_count + empty_sensor_window_count)),
                gaps=str(max(0, gap_count)),
                overlaps=str(max(0, overlap_count)),
                dropped=str(max(0, dropped_chunk_count)),
                late=str(max(0, late_packet_chunk_count)),
                udp_ingest=str(max(0, udp_ingest_queue_drop_count)),
                queue_overflow=str(max(0, queue_overflow_chunk_count)),
                invalid=str(max(0, invalid_chunk_count)),
                write_errors=str(max(0, write_error_chunk_count)),
                mismatches=str(max(0, sample_rate_mismatch_sensor_count)),
                unverified_rates=str(max(0, sample_rate_unverified_sensor_count)),
                legacy=str(max(0, legacy_sensor_count)),
                unanchored=str(max(0, unanchored_sensor_count)),
                sync_unverified=str(max(0, sync_unverified_sensor_count)),
                missing_sync=str(max(0, missing_sync_sensor_count)),
                stale=str(max(0, stale_sync_sensor_count)),
                high_rtt=str(max(0, high_rtt_sensor_count)),
            ),
        ),
    )


def whole_run_window_spectral_summaries_to_jsonl_bytes(
    summaries: Sequence[WholeRunWindowSpectralSummary],
) -> bytes:
    return jsonl_bytes_from_objects(summaries)


def whole_run_window_spectral_summaries_from_jsonl_bytes(
    payload: bytes,
) -> tuple[WholeRunWindowSpectralSummary, ...]:
    """Reconstruct persisted whole-run spectral summaries from sidecar JSONL bytes."""

    return jsonl_objects_from_bytes(
        payload,
        context="whole-run spectral summaries",
        line_description="whole-run spectral summary line",
        from_mapping=WholeRunWindowSpectralSummary.from_mapping,
    )


def whole_run_spectral_summaries_by_sensor(
    *,
    manifest: WholeRunArtifactManifest,
    artifact_contents: Mapping[str, bytes],
) -> dict[str, tuple[WholeRunWindowSpectralSummary, ...]]:
    """Load deterministic whole-run spectral summary rows keyed by sensor id."""

    summaries_by_sensor: dict[str, tuple[WholeRunWindowSpectralSummary, ...]] = {}
    summary_artifacts = sorted(
        (
            artifact
            for artifact in manifest.artifacts
            if artifact.artifact_key.startswith("spectral-summary:")
        ),
        key=lambda artifact: (artifact.sensor_id or "", artifact.artifact_key),
    )
    for artifact in summary_artifacts:
        if artifact.sensor_id is None:
            raise ValueError("whole-run spectral summary artifacts require sensor_id for loading")
        payload = artifact_contents.get(artifact.artifact_key)
        if payload is None:
            raise ValueError(
                f"whole-run spectral summaries missing bytes for {artifact.artifact_key}"
            )
        summaries = whole_run_window_spectral_summaries_from_jsonl_bytes(payload)
        if len(summaries) != manifest.total_window_count:
            raise ValueError(
                "whole-run spectral summaries require one row per window "
                f"for {artifact.artifact_key}"
            )
        summaries_by_sensor[artifact.sensor_id] = summaries
    return summaries_by_sensor


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _int_or_default(value: object, *, default: int) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None else default


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _coverage_state(value: object) -> RawCaptureCoverageState:
    if value in {"missing", "empty", "partial", "full"}:
        return cast(RawCaptureCoverageState, value)
    return "missing"
