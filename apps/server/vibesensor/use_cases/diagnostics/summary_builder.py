"""Structured orchestration for building analysis summaries from run samples."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from statistics import median as _median
from typing import cast

from vibesensor.domain import (
    ConfigurationSnapshot,
    DiagnosticCase,
    DrivingPhaseInterval,
    LocationIntensitySummary,
    RunCapture,
    RunSetup,
    RunSuitability,
    Sensor,
    SpeedProfile,
    SpeedSource,
    TestRun,
)
from vibesensor.domain import (
    DrivingSegment as DomainDrivingSegment,
)
from vibesensor.domain import (
    Finding as DomainFinding,
)
from vibesensor.domain.snapshots import DrivingPhaseSummary, SpeedProfileSummary
from vibesensor.domain.test_plan import plan_test_actions
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.report_i18n import normalize_lang
from vibesensor.shared.boundaries.analysis_payload import (
    AnalysisSummary,
    FindingPayload,
    PhaseSpeedBreakdownRow,
    SpeedBreakdownRow,
)
from vibesensor.shared.boundaries.diagnostic_case import (
    case_context_from_metadata,
    speed_profile_from_stats,
)
from vibesensor.shared.boundaries.finding import step_payloads_from_plan
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.json_utils import i18n_ref
from vibesensor.shared.run_context import build_summary_warnings
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.use_cases.diagnostics._types import (
    AccelStatistics,
    Sample,
)
from vibesensor.use_cases.diagnostics.findings import (
    _build_findings,
    _phase_speed_breakdown,
    _sensor_intensity_by_location,
    _speed_breakdown,
)
from vibesensor.use_cases.diagnostics.helpers import (
    _load_run,
    _location_label,
    _locations_connected_throughout_run,
    _run_noise_baseline_g,
    _validate_required_strength_metrics,
)
from vibesensor.use_cases.diagnostics.phase_segmentation import (
    DrivingPhase,
    PhaseSegment,
)
from vibesensor.use_cases.diagnostics.plots import _plot_data
from vibesensor.use_cases.diagnostics.speed_profile_helpers import (
    _speed_stats,
    _speed_stats_by_phase,
)
from vibesensor.use_cases.diagnostics.statistics import (
    _strength_band_key,
    compute_accel_statistics,
    compute_frame_integrity_counts,
    compute_reference_completeness,
    compute_run_timing,
    prepare_speed_and_phases,
)
from vibesensor.use_cases.diagnostics.summary_serialization import (
    annotate_peaks_with_order_labels,
    build_summary_payload,
)
from vibesensor.use_cases.diagnostics.top_cause_selection import select_top_causes

# ═══════════════════════════════════════════════════════════════════════════
# Phase timeline and driving segments
# ═══════════════════════════════════════════════════════════════════════════


def build_phase_timeline(
    phase_segments: list[PhaseSegment],
    findings: Sequence[DomainFinding],
    *,
    min_confidence: float,
) -> list[DrivingPhaseInterval]:
    """Build a simple phase timeline annotated with finding evidence."""
    if not phase_segments:
        return []

    # NOTE: has_fault_evidence is always False because phases_detected is not
    # preserved on the domain Finding (only cruise_fraction survives the
    # payload→domain decode).  Keeping the field for schema stability.
    return [
        DrivingPhaseInterval(
            phase=segment.phase,
            start_t_s=None if math.isnan(segment.start_t_s) else segment.start_t_s,
            end_t_s=None if math.isnan(segment.end_t_s) else segment.end_t_s,
            speed_min_kmh=segment.speed_min_kmh,
            speed_max_kmh=segment.speed_max_kmh,
            has_fault_evidence=False,
        )
        for segment in phase_segments
    ]


def build_domain_driving_segments(
    phase_segments: list[PhaseSegment],
) -> tuple[DomainDrivingSegment, ...]:
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


# ═══════════════════════════════════════════════════════════════════════════
# Sensor analysis and summary helpers
# ═══════════════════════════════════════════════════════════════════════════


def build_sensor_analysis(
    *,
    samples: list[Sample],
    language: str,
    per_sample_phases: list[DrivingPhase],
) -> tuple[list[str], set[str], list[LocationIntensitySummary]]:
    """Build sensor location lists and intensity rows from analysed samples."""
    sensor_locations = sorted(
        {
            label
            for sample in samples
            if isinstance(sample, dict) and (label := _location_label(sample, lang=language))
        },
    )
    connected_locations = _locations_connected_throughout_run(samples, lang=language)
    sensor_intensity_by_location = _sensor_intensity_by_location(
        samples,
        include_locations=set(sensor_locations),
        lang=language,
        connected_locations=connected_locations,
        per_sample_phases=per_sample_phases,
    )
    return sensor_locations, connected_locations, sensor_intensity_by_location


def summarize_origin(
    findings: tuple[DomainFinding, ...],
) -> VibrationOrigin | None:
    """Return the most-likely origin as a domain value object."""
    return VibrationOrigin.from_ranked_findings(findings)


# ═══════════════════════════════════════════════════════════════════════════
# Main orchestration
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class PreparedRunData:
    """Input coordinator: shared timing, speed, and phase context for summary generation.

    Retained as the canonical input coordinator for the analysis pipeline.
    Computed once by :func:`prepare_run_data` and consumed by
    :func:`build_findings_bundle`, :func:`build_run_suitability_bundle`,
    and :class:`RunAnalysis`.
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
    speed_breakdown: list[SpeedBreakdownRow]
    speed_breakdown_skipped_reason: JsonObject | None
    phase_speed_breakdown: list[PhaseSpeedBreakdownRow]

    # -- derived convenience ------------------------------------------------

    @property
    def is_steady_speed(self) -> bool:
        """Whether the run had steady speed (relevant to confidence scoring)."""
        steady: bool = self.speed_profile.steady_speed
        return steady

    @property
    def speed_stddev_kmh(self) -> float | None:
        return self.speed_profile.stddev_kmh if self.speed_values else None


def prepare_run_data(
    metadata: JsonObject,
    samples: list[Sample],
    *,
    file_name: str,
) -> PreparedRunData:
    """Prepare shared timing, speed, and phase context for summary generation."""
    run_id, start_ts, end_ts, duration_s = compute_run_timing(metadata, samples, file_name)
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
        raw_sample_rate_hz=_as_float(metadata.get("raw_sample_rate_hz")),
        speed_values=speed_values,
        speed_non_null_pct=speed_non_null_pct,
        speed_sufficient=speed_sufficient,
        per_sample_phases=per_sample_phases,
        phase_segments=phase_segments,
        run_noise_baseline_g=run_noise_baseline_g,
        speed_profile=speed_profile_from_stats(
            speed_stats,
            phase_info,
        ),
        speed_stats_by_phase=_speed_stats_by_phase(samples, per_sample_phases),
        speed_breakdown=speed_breakdown,
        speed_breakdown_skipped_reason=speed_breakdown_skipped_reason,
        phase_speed_breakdown=_phase_speed_breakdown(samples, per_sample_phases),
    )


def build_phase_summary(phase_segments: list[PhaseSegment]) -> DrivingPhaseSummary:
    """Small wrapper to keep summary-building imports localized."""
    from vibesensor.use_cases.diagnostics.phase_segmentation import phase_summary

    return phase_summary(phase_segments)


def build_findings_bundle(
    metadata: JsonObject,
    samples: list[Sample],
    *,
    language: str,
    prepared: PreparedRunData,
    overall_strength_band_key: str | None,
    has_reference_gaps: bool,
    sensor_count: int,
    findings_builder: Callable[..., tuple[DomainFinding, ...]] | None = None,
) -> tuple[
    VibrationOrigin | None,
    list[DrivingPhaseInterval],
    tuple[DomainFinding, ...],
    tuple[DomainFinding, ...],
]:
    """Build findings plus derived diagnosis narrative fields.

    Returns ``(origin, timeline, domain_findings, domain_top_causes)``.
    Findings are returned with :class:`ConfidenceAssessment` already
    attached via :meth:`Finding.with_confidence_assessment`.
    """
    builder = findings_builder or _build_findings
    domain_findings = builder(
        metadata=metadata,
        samples=samples,
        speed_sufficient=prepared.speed_sufficient,
        steady_speed=prepared.is_steady_speed,
        speed_stddev_kmh=prepared.speed_stddev_kmh,
        speed_non_null_pct=prepared.speed_non_null_pct,
        raw_sample_rate_hz=prepared.raw_sample_rate_hz,
        lang=language,
        per_sample_phases=prepared.per_sample_phases,
        run_noise_baseline_g=prepared.run_noise_baseline_g,
    )

    # Enrich findings with ConfidenceAssessment at construction time
    domain_findings = tuple(
        f
        if f.confidence_assessment is not None
        else f.with_confidence_assessment(
            strength_band_key=overall_strength_band_key or "",
            steady_speed=prepared.is_steady_speed,
            has_reference_gaps=has_reference_gaps,
            sensor_count=sensor_count,
        )
        for f in domain_findings
    )

    domain_diagnostic_findings = tuple(f for f in domain_findings if not f.is_reference)
    most_likely_origin = summarize_origin(
        domain_diagnostic_findings,
    )
    phase_timeline = build_phase_timeline(
        prepared.phase_segments,
        domain_findings,
        min_confidence=0.25,
    )
    domain_top_causes = select_top_causes(
        domain_findings,
    )
    return (
        most_likely_origin,
        phase_timeline,
        domain_findings,
        domain_top_causes,
    )


def build_sensor_bundle(
    samples: list[Sample],
    *,
    language: str,
    per_sample_phases: list[DrivingPhase],
) -> tuple[list[str], set[str], list[LocationIntensitySummary]]:
    """Build location-scoped sensor summaries used by analysis and reports."""
    return build_sensor_analysis(
        samples=samples,
        language=language,
        per_sample_phases=per_sample_phases,
    )


def build_run_suitability_bundle(
    metadata: JsonObject,
    samples: list[Sample],
    *,
    prepared: PreparedRunData,
    accel_stats: AccelStatistics,
) -> tuple[bool, RunSuitability | None, str | None]:
    """Build run-suitability checks and related confidence context."""
    reference_complete = compute_reference_completeness(metadata)
    sensor_ids = {
        str(cid)
        for sample in samples
        if isinstance(sample, dict) and (cid := sample.get("client_id"))
    }
    total_dropped, total_overflow = compute_frame_integrity_counts(samples)
    run_suitability = RunSuitability.evaluate(
        steady_speed=prepared.is_steady_speed,
        speed_sufficient=prepared.speed_sufficient,
        sensor_count=len(sensor_ids),
        reference_complete=reference_complete,
        sat_count=accel_stats["sat_count"],
        total_dropped=total_dropped,
        total_overflow=total_overflow,
    )
    amp_metric_values = accel_stats["amp_metric_values"]
    overall_strength_band_key = (
        _strength_band_key(_median(amp_metric_values)) if amp_metric_values else None
    )
    return reference_complete, run_suitability, overall_strength_band_key


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Output coordinator: carries domain aggregates alongside the boundary summary dict.

    Returned by :meth:`RunAnalysis.summarize`.  The ``summary`` dict is
    still needed for persistence (SQLite stores it as JSON) and many
    existing boundary consumers.  ``test_run`` and ``diagnostic_case``
    expose the fully-constructed domain aggregates so that callers no
    longer need to discard them.
    """

    test_run: TestRun
    diagnostic_case: DiagnosticCase
    summary: AnalysisSummary


class RunAnalysis:
    """Cohesive object around a single analyzed run.

    Owns run timing, speed/phase preparation, data quality, suitability,
    sensor bundle, findings bundle, and summary export.  Replaces the
    procedural orchestration in ``summarize_run_data`` with a richer
    object that keeps all derived state together.

    The public ``summarize_run_data()`` function delegates here.
    """

    __slots__ = (
        "_metadata",
        "_samples",
        "_file_name",
        "_language",
        "_include_samples",
        "_findings_builder",
        "_prepared",
        "_accel_stats",
        "_test_run",
    )

    def __init__(
        self,
        metadata: JsonObject,
        samples: list[Sample],
        *,
        file_name: str = "run",
        lang: str | None = None,
        include_samples: bool = True,
        findings_builder: Callable[..., tuple[DomainFinding, ...]] | None = None,
    ) -> None:
        self._metadata = metadata
        self._samples = samples
        self._file_name = file_name
        self._language = normalize_lang(lang)
        self._include_samples = include_samples
        self._findings_builder = findings_builder
        self._test_run: TestRun | None = None

        _validate_required_strength_metrics(samples)
        self._prepared = prepare_run_data(metadata, samples, file_name=file_name)
        self._accel_stats: AccelStatistics = compute_accel_statistics(
            samples, metadata.get("sensor_model")
        )

    # -- read-only access --------------------------------------------------

    @property
    def prepared(self) -> PreparedRunData:
        return self._prepared

    @property
    def accel_stats(self) -> AccelStatistics:
        return self._accel_stats

    @property
    def language(self) -> str:
        lang: str = self._language
        return lang

    @property
    def test_run(self) -> TestRun | None:
        return self._test_run

    # -- orchestration -----------------------------------------------------

    def summarize(self) -> AnalysisResult:
        """Run the full analysis pipeline and return the output coordinator.

        Returns an :class:`AnalysisResult` carrying the domain aggregates
        (``test_run``, ``diagnostic_case``) alongside the boundary
        ``summary`` dict.
        """
        reference_complete, run_suitability, overall_strength_band_key = (
            build_run_suitability_bundle(
                self._metadata,
                self._samples,
                prepared=self._prepared,
                accel_stats=self._accel_stats,
            )
        )
        sensor_locations, connected_locations, sensor_intensity_by_location = build_sensor_bundle(
            self._samples,
            language=self._language,
            per_sample_phases=self._prepared.per_sample_phases,
        )
        (
            most_likely_origin,
            phase_timeline,
            domain_findings,
            domain_top_causes,
        ) = build_findings_bundle(
            self._metadata,
            self._samples,
            language=self._language,
            prepared=self._prepared,
            overall_strength_band_key=overall_strength_band_key,
            has_reference_gaps=not reference_complete,
            sensor_count=len(sensor_locations),
            findings_builder=self._findings_builder,
        )

        # Build the domain aggregate with run-level value objects
        speed_profile = self._prepared.speed_profile if self._prepared.speed_values else None
        domain_suitability = run_suitability

        # Derive top_causes as a subset of the enriched findings,
        # preserving signatures collected by group_findings_by_source
        top_cause_ids = {f.finding_id for f in domain_top_causes if f.finding_id}
        top_cause_sigs = {f.finding_id: f.signatures for f in domain_top_causes if f.signatures}
        final_top_causes_list: list[DomainFinding] = []
        for f in domain_findings:
            if f.finding_id in top_cause_ids:
                sigs = top_cause_sigs.get(f.finding_id)
                final_top_causes_list.append(replace(f, signatures=sigs) if sigs else f)
        final_top_causes = tuple(final_top_causes_list)

        configuration_snapshot = ConfigurationSnapshot.from_metadata(self._metadata)
        driving_segments = build_domain_driving_segments(self._prepared.phase_segments)
        domain_test_plan = plan_test_actions(domain_findings)
        summary_test_plan: list[JsonObject] = cast(
            list[JsonObject], step_payloads_from_plan(domain_test_plan)
        )
        _raw_settings = self._metadata.get("analysis_settings")
        _scalar_settings: list[tuple[str, int | float | bool | str]] = []
        if isinstance(_raw_settings, dict):
            for _k, _v in sorted(_raw_settings.items()):
                if isinstance(_v, (int, float, bool, str)):
                    _scalar_settings.append((_k, _v))
        capture = RunCapture(
            run_id=self._prepared.run_id,
            setup=RunSetup(
                sensors=Sensor.from_location_codes(sensor_locations) if sensor_locations else (),
                speed_source=SpeedSource(),
                configuration_snapshot=configuration_snapshot,
            ),
            analysis_settings=tuple(_scalar_settings),
            sample_count=len(self._samples),
            duration_s=self._prepared.duration_s,
        )
        self._test_run = TestRun(
            capture=capture,
            driving_segments=driving_segments,
            findings=domain_findings,
            top_causes=final_top_causes,
            speed_profile=speed_profile,
            suitability=domain_suitability,
            test_plan=domain_test_plan,
        )
        domain_car, domain_symptoms = case_context_from_metadata(self._metadata)
        diagnostic_case = DiagnosticCase.start(
            car=domain_car,
            symptoms=domain_symptoms,
            test_plan=domain_test_plan,
        ).add_run(self._test_run)

        summary_speed_stats = _speed_stats(self._prepared.speed_values)
        summary_phase_info = build_phase_summary(self._prepared.phase_segments)

        # Serialize domain findings to payloads for the summary
        from vibesensor.shared.boundaries.finding import finding_payload_from_domain

        findings: list[FindingPayload] = [
            cast(FindingPayload, finding_payload_from_domain(f)) for f in domain_findings
        ]
        top_causes: list[FindingPayload] = [
            cast(FindingPayload, finding_payload_from_domain(f)) for f in final_top_causes
        ]

        summary = build_summary_payload(
            file_name=self._file_name,
            run_id=self._prepared.run_id,
            samples=self._samples,
            duration_s=self._prepared.duration_s,
            language=self._language,
            metadata=self._metadata,
            raw_sample_rate_hz=self._prepared.raw_sample_rate_hz,
            speed_breakdown=self._prepared.speed_breakdown,
            phase_speed_breakdown=self._prepared.phase_speed_breakdown,
            phase_segments=self._prepared.phase_segments,
            run_noise_baseline_g=self._prepared.run_noise_baseline_g,
            speed_breakdown_skipped_reason=self._prepared.speed_breakdown_skipped_reason,
            findings=findings,
            top_causes=top_causes,
            most_likely_origin=most_likely_origin,
            test_plan=summary_test_plan,
            phase_timeline=phase_timeline,
            speed_stats=summary_speed_stats,
            speed_stats_by_phase=self._prepared.speed_stats_by_phase,
            phase_info=summary_phase_info,
            sensor_locations=sensor_locations,
            connected_locations=connected_locations,
            sensor_intensity_by_location=sensor_intensity_by_location,
            run_suitability=domain_suitability,
            speed_values=self._prepared.speed_values,
            speed_non_null_pct=self._prepared.speed_non_null_pct,
            accel_stats=self._accel_stats,
            amp_metric_values=self._accel_stats["amp_metric_values"],
        )
        summary["warnings"] = build_summary_warnings(
            self._metadata,
            reference_complete=reference_complete,
        )
        summary["report_date"] = self._metadata.get("end_time_utc") or utc_now_iso()
        summary["plots"] = _plot_data(
            summary,
            run_noise_baseline_g=self._prepared.run_noise_baseline_g,
            per_sample_phases=self._prepared.per_sample_phases,
            phase_segments=self._prepared.phase_segments,
        )
        annotate_peaks_with_order_labels(summary)
        cast(dict[str, object], summary)["_summary_version"] = 2
        if not self._include_samples:
            summary.pop("samples", None)
        return AnalysisResult(
            test_run=self._test_run,
            diagnostic_case=diagnostic_case,
            summary=summary,
        )


def summarize_run_data(
    metadata: JsonObject,
    samples: list[Sample],
    lang: str | None = None,
    file_name: str = "run",
    include_samples: bool = True,
    findings_builder: Callable[..., tuple[DomainFinding, ...]] | None = None,
) -> AnalysisSummary:
    """Analyze pre-loaded run data and return the full summary dict.

    Delegates to :class:`RunAnalysis` which owns the full orchestration.
    """
    return (
        RunAnalysis(
            metadata,
            samples,
            file_name=file_name,
            lang=lang,
            include_samples=include_samples,
            findings_builder=findings_builder,
        )
        .summarize()
        .summary
    )


def build_findings_for_samples(
    *,
    metadata: JsonObject,
    samples: list[Sample],
    lang: str | None = None,
    findings_builder: Callable[..., tuple[DomainFinding, ...]] | None = None,
) -> tuple[DomainFinding, ...]:
    """Build the findings list from *samples* using the full analysis pipeline."""
    language = normalize_lang(lang)
    rows = list(samples)
    _validate_required_strength_metrics(rows)
    prepared = prepare_run_data(metadata, rows, file_name="run")
    builder = findings_builder or _build_findings
    return builder(
        metadata=dict(metadata),
        samples=rows,
        speed_sufficient=prepared.speed_sufficient,
        steady_speed=prepared.is_steady_speed,
        speed_stddev_kmh=prepared.speed_stddev_kmh,
        speed_non_null_pct=prepared.speed_non_null_pct,
        raw_sample_rate_hz=prepared.raw_sample_rate_hz,
        lang=language,
        per_sample_phases=prepared.per_sample_phases,
    )


def summarize_log(
    log_path: Path,
    lang: str | None = None,
    include_samples: bool = True,
    findings_builder: Callable[..., tuple[DomainFinding, ...]] | None = None,
) -> AnalysisSummary:
    """Read a JSONL run file and analyse it."""
    metadata, samples, _warnings = _load_run(log_path)
    return summarize_run_data(
        metadata,
        samples,
        lang=lang,
        file_name=log_path.name,
        include_samples=include_samples,
        findings_builder=findings_builder,
    )
