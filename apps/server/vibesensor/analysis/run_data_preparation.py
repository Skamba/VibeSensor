"""Run-level data preparation helpers for diagnostics summary building."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from vibesensor.analysis._sample_metrics import _run_noise_baseline_g
from vibesensor.analysis._types import Sample
from vibesensor.analysis._view_types import (
    PhaseSpeedBreakdownRowData,
    SpeedBreakdownRowData,
)
from vibesensor.analysis.phase_segmentation import DrivingPhase, PhaseSegment
from vibesensor.analysis.signal_aggregation import (
    _phase_speed_breakdown,
    _speed_breakdown,
)
from vibesensor.analysis.speed_profile_helpers import _speed_stats_by_phase
from vibesensor.analysis.statistics import (
    compute_run_timing,
    prepare_speed_and_phases,
)
from vibesensor.common.json_types import JsonObject
from vibesensor.common.json_utils import i18n_ref
from vibesensor.domain.driving_phase_summary import DrivingPhaseSummary
from vibesensor.domain.speed_profile import SpeedProfile
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.recording.run_schema import RunMetadata


@dataclass(frozen=True)
class PreparedRunData:
    """Input coordinator: shared timing, speed, and phase context for summary generation.

    Retained as the canonical input coordinator for the analysis pipeline.
    Computed once by :func:`prepare_run_data` and consumed by
    :func:`vibesensor.analysis.findings_bundle.build_findings_bundle`,
    :func:`vibesensor.analysis.prepared_analysis_context.prepare_analysis_context`,
    and :class:`vibesensor.analysis.run_analysis.RunAnalysis`.
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
    context: RunMetadata,
    samples: Sequence[Sample],
) -> PreparedRunData:
    """Prepare shared timing, speed, and phase context for summary generation."""
    run_id, start_ts, end_ts, duration_s = compute_run_timing(context, samples)
    (
        speed_values,
        speed_stats,
        speed_non_null_pct,
        speed_sufficient,
        per_sample_phases,
        phase_segments,
    ) = prepare_speed_and_phases(samples)
    run_noise_baseline_g = _run_noise_baseline_g(samples)
    speed_breakdown = _speed_breakdown(samples) if speed_sufficient else []
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
        speed_stats_by_phase=_speed_stats_by_phase(samples, per_sample_phases),
        speed_breakdown=speed_breakdown,
        speed_breakdown_skipped_reason=speed_breakdown_skipped_reason,
        phase_speed_breakdown=_phase_speed_breakdown(samples, per_sample_phases),
    )


def build_phase_summary(phase_segments: Sequence[PhaseSegment]) -> DrivingPhaseSummary:
    """Small wrapper to keep phase-summary imports localized."""
    from vibesensor.analysis.phase_segmentation import phase_summary

    return phase_summary(list(phase_segments))
