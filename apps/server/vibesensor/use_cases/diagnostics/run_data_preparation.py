"""Run-level data preparation helpers for diagnostics summary building."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from vibesensor.domain import (
    DrivingPhaseInterval,
    LocationIntensitySummary,
    SpeedProfile,
)
from vibesensor.domain import (
    DrivingSegment as DomainDrivingSegment,
)
from vibesensor.domain import (
    Finding as DomainFinding,
)
from vibesensor.domain.driving_phase_summary import DrivingPhaseSummary
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.shared.json_utils import i18n_ref
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.use_cases.diagnostics._context import DiagnosticsContext
from vibesensor.use_cases.diagnostics._sample_metrics import _run_noise_baseline_g
from vibesensor.use_cases.diagnostics._sensor_locations import (
    _location_label,
    _locations_connected_throughout_run,
)
from vibesensor.use_cases.diagnostics._types import (
    AnalysisSampleInput,
    Sample,
    ensure_analysis_samples,
)
from vibesensor.use_cases.diagnostics._view_types import (
    PhaseSpeedBreakdownRowData,
    SpeedBreakdownRowData,
)
from vibesensor.use_cases.diagnostics.phase_segmentation import (
    DrivingPhase,
    PhaseSegment,
)
from vibesensor.use_cases.diagnostics.signal_aggregation import (
    _phase_speed_breakdown_samples,
    _sensor_intensity_by_location_samples,
    _speed_breakdown_samples,
)
from vibesensor.use_cases.diagnostics.speed_profile_helpers import _speed_stats_by_phase_samples
from vibesensor.use_cases.diagnostics.statistics import (
    _compute_run_timing,
    _prepare_speed_and_phases,
)


def build_phase_timeline(
    phase_segments: Sequence[PhaseSegment],
    findings: Sequence[DomainFinding],
    *,
    min_confidence: float,
) -> list[DrivingPhaseInterval]:
    """Build a simple phase timeline annotated with finding evidence."""
    if not phase_segments:
        return []

    evidence_phases = {
        str(phase).strip().lower()
        for finding in findings
        if finding.is_diagnostic and finding.effective_confidence >= min_confidence
        for phase in finding.phases_detected
        if str(phase).strip()
    }
    return [
        DrivingPhaseInterval(
            phase=segment.phase,
            start_t_s=None if math.isnan(segment.start_t_s) else segment.start_t_s,
            end_t_s=None if math.isnan(segment.end_t_s) else segment.end_t_s,
            speed_min_kmh=segment.speed_min_kmh,
            speed_max_kmh=segment.speed_max_kmh,
            has_fault_evidence=str(segment.phase).strip().lower() in evidence_phases,
        )
        for segment in phase_segments
    ]


def build_domain_driving_segments(
    phase_segments: Sequence[PhaseSegment],
) -> tuple[DomainDrivingSegment, ...]:
    """Project diagnostics phase segments into the domain driving-segment shape."""
    return tuple(
        DomainDrivingSegment(
            phase=segment.phase,
            start_idx=segment.start_idx,
            end_idx=segment.end_idx,
            start_t_s=(
                None
                if isinstance(segment.start_t_s, float) and math.isnan(segment.start_t_s)
                else segment.start_t_s
            ),
            end_t_s=(
                None
                if isinstance(segment.end_t_s, float) and math.isnan(segment.end_t_s)
                else segment.end_t_s
            ),
            speed_min_kmh=segment.speed_min_kmh,
            speed_max_kmh=segment.speed_max_kmh,
            sample_count=segment.sample_count,
        )
        for segment in phase_segments
    )


def build_sensor_analysis(
    *,
    samples: Sequence[Sample],
    language: str,
    per_sample_phases: Sequence[DrivingPhase],
) -> tuple[list[str], set[str], list[LocationIntensitySummary]]:
    """Build sensor location lists and intensity rows from analysed samples."""
    sensor_locations = sorted(
        {label for sample in samples if (label := _location_label(sample, lang=language))},
    )
    connected_locations = _locations_connected_throughout_run(samples, lang=language)
    sensor_intensity_by_location = _sensor_intensity_by_location_samples(
        samples,
        include_locations=set(sensor_locations),
        lang=language,
        connected_locations=connected_locations,
        per_sample_phases=per_sample_phases,
    )
    return sensor_locations, connected_locations, sensor_intensity_by_location


@dataclass(frozen=True)
class PreparedRunData:
    """Input coordinator: shared timing, speed, and phase context for summary generation.

    Retained as the canonical input coordinator for the analysis pipeline.
    Computed once by :func:`prepare_run_data` and consumed by
    :func:`vibesensor.use_cases.diagnostics._summary_steps.build_findings_bundle`,
    :func:`vibesensor.use_cases.diagnostics._summary_steps.build_run_suitability_bundle`,
    and :class:`vibesensor.use_cases.diagnostics.summary_builder.RunAnalysis`.
    """

    run_id: str
    start_ts: datetime | None
    end_ts: datetime | None
    duration_s: float
    raw_sample_rate_hz: float | None
    speed_values: list[float]
    speed_non_null_pct: float
    speed_sufficient: bool
    per_sample_phases: list[DrivingPhase]
    phase_segments: list[PhaseSegment]
    run_noise_baseline_g: float | None
    speed_profile: SpeedProfile
    speed_stats_by_phase: dict[str, SpeedProfileSummary]
    speed_breakdown: list[SpeedBreakdownRowData]
    speed_breakdown_skipped_reason: JsonObject | None
    phase_speed_breakdown: list[PhaseSpeedBreakdownRowData]

    @property
    def is_steady_speed(self) -> bool:
        """Whether the run had steady speed (relevant to confidence scoring)."""
        steady: bool = self.speed_profile.steady_speed
        return steady

    @property
    def speed_stddev_kmh(self) -> float | None:
        return self.speed_profile.stddev_kmh if self.speed_values else None


def prepare_run_data(
    context: DiagnosticsContext,
    samples: Sequence[AnalysisSampleInput],
) -> PreparedRunData:
    """Prepare shared timing, speed, and phase context for summary generation."""
    return _prepare_run_data(context, ensure_analysis_samples(samples))


def _prepare_run_data(
    context: DiagnosticsContext,
    samples: Sequence[Sample],
) -> PreparedRunData:
    """Prepare shared timing, speed, and phase context for summary generation."""
    run_id, start_ts, end_ts, duration_s = _compute_run_timing(context, samples)
    (
        speed_values,
        speed_stats,
        speed_non_null_pct,
        speed_sufficient,
        per_sample_phases,
        phase_segments,
    ) = _prepare_speed_and_phases(samples)
    run_noise_baseline_g = _run_noise_baseline_g(samples)
    speed_breakdown = _speed_breakdown_samples(samples) if speed_sufficient else []
    speed_breakdown_skipped_reason: JsonObject | None = None
    if not speed_sufficient:
        speed_breakdown_skipped_reason = i18n_ref(
            "SPEED_DATA_MISSING_OR_INSUFFICIENT_SPEED_BINNED_AND",
        )
    phase_info = build_phase_summary(phase_segments)

    return PreparedRunData(
        run_id=run_id,
        start_ts=start_ts,
        end_ts=end_ts,
        duration_s=duration_s,
        raw_sample_rate_hz=context.raw_sample_rate_hz,
        speed_values=speed_values,
        speed_non_null_pct=speed_non_null_pct,
        speed_sufficient=speed_sufficient,
        per_sample_phases=per_sample_phases,
        phase_segments=phase_segments,
        run_noise_baseline_g=run_noise_baseline_g,
        speed_profile=SpeedProfile.from_stats(
            speed_stats,
            phase_info,
        ),
        speed_stats_by_phase=_speed_stats_by_phase_samples(samples, per_sample_phases),
        speed_breakdown=speed_breakdown,
        speed_breakdown_skipped_reason=speed_breakdown_skipped_reason,
        phase_speed_breakdown=_phase_speed_breakdown_samples(samples, per_sample_phases),
    )


def build_phase_summary(phase_segments: Sequence[PhaseSegment]) -> DrivingPhaseSummary:
    """Small wrapper to keep phase-summary imports localized."""
    from vibesensor.use_cases.diagnostics.phase_segmentation import phase_summary

    return phase_summary(list(phase_segments))
