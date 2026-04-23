"""Semantic prepared reporting facts shared across presentation and rendering."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.shared.boundaries.codecs.scalars import coerce_count, text_or_none
from vibesensor.shared.json_utils import i18n_ref
from vibesensor.shared.run_context_warning import (
    WARNING_CODE_WHOLE_RUN_CONTEXT_INCOMPLETE,
    WARNING_CODE_WHOLE_RUN_CONTEXT_LEGACY_FALLBACK,
    RunContextWarning,
)

if TYPE_CHECKING:
    from vibesensor.domain import (
        TestRun,
        VibrationOrigin,
    )
    from vibesensor.shared.boundaries.reporting.confidence_facts import ReportConfidenceFacts
    from vibesensor.shared.boundaries.reporting.decision_facts import ReportDecisionFacts
    from vibesensor.shared.boundaries.reporting.evidence_facts import ReportEvidenceFacts
    from vibesensor.shared.boundaries.reporting.findings import PreparedReportFindings
    from vibesensor.shared.boundaries.reporting.sensor_facts import ReportSensorFacts
    from vibesensor.shared.boundaries.reporting.summary import (
        NormalizedReportSummary,
        ReportTimelineInterval,
        ReportWholeRunContextInterval,
    )
    from vibesensor.shared.types.analysis_views import PeakTableRow

from vibesensor.shared.boundaries.reporting.confidence_facts import build_report_confidence_facts
from vibesensor.shared.boundaries.reporting.decision_facts import (
    ActionStatusKey,
    LocationConfidenceKey,
    build_report_decision_facts,
)
from vibesensor.shared.boundaries.reporting.evidence_facts import build_report_evidence_facts
from vibesensor.shared.boundaries.reporting.findings import (
    PreparedReportFindings,
    prepare_report_findings,
)
from vibesensor.shared.boundaries.reporting.projection import (
    normalize_origin_location,
    resolve_report_origin,
)
from vibesensor.shared.boundaries.reporting.sensor_facts import (
    build_report_sensor_facts,
    enrich_location_proof_sensor_facts,
)
from vibesensor.shared.run_context_warning import RunContextWarningsInput

__all__ = [
    "ActionStatusKey",
    "LocationConfidenceKey",
    "ReportContextFacts",
    "PreparedReportFacts",
    "ReportRunFacts",
    "prepare_report_facts",
]


@dataclass(frozen=True, slots=True)
class ReportRunFacts:
    """Run-scoped report facts independent from sensor and decision shaping."""

    run_id: str
    origin: VibrationOrigin | None
    origin_location: str
    report_date: str | None
    recorded_utc_offset_seconds: int | None
    duration_s: float | None
    duration_text: str | None
    start_time_utc: str | None
    end_time_utc: str | None
    sample_rate_hz: str | None
    tire_spec_text: str | None
    sample_count: int
    sensor_count: int
    sensor_model: str | None
    firmware_version: str | None
    car_name: str | None
    car_type: str | None
    timeline_intervals: tuple[ReportTimelineInterval, ...]
    peak_table_rows: tuple[PeakTableRow, ...]


@dataclass(frozen=True, slots=True)
class ReportContextFacts:
    """Traceability-friendly whole-run context facts for persisted history/report prep."""

    traceable: bool
    source: str
    interval_count: int
    intervals: tuple[ReportWholeRunContextInterval, ...]
    window_count: int | None
    full_window_count: int
    partial_window_count: int
    missing_window_count: int
    missing_speed_window_count: int
    missing_rpm_window_count: int
    stale_speed_window_count: int
    stale_rpm_window_count: int
    warnings: tuple[RunContextWarning, ...]

    @property
    def has_incomplete_context(self) -> bool:
        return (
            self.traceable
            and self.source == "whole_run"
            and (self.partial_window_count > 0 or self.missing_window_count > 0)
        )

    @property
    def speed_gap_window_count(self) -> int:
        return self.missing_speed_window_count + self.stale_speed_window_count

    @property
    def rpm_gap_window_count(self) -> int:
        return self.missing_rpm_window_count + self.stale_rpm_window_count

    @property
    def has_speed_gaps(self) -> bool:
        return self.traceable and self.source == "whole_run" and self.speed_gap_window_count > 0

    @property
    def has_rpm_gaps(self) -> bool:
        return self.traceable and self.source == "whole_run" and self.rpm_gap_window_count > 0


@dataclass(frozen=True, slots=True)
class PreparedReportFacts:
    """Canonical grouped report facts for run, sensor, and decision concerns."""

    run: ReportRunFacts
    context: ReportContextFacts
    sensor: ReportSensorFacts
    decision: ReportDecisionFacts
    evidence: ReportEvidenceFacts
    confidence: ReportConfidenceFacts
    findings: PreparedReportFindings


def prepare_report_facts(
    payload: Mapping[str, object],
    *,
    summary: NormalizedReportSummary,
    test_run: TestRun,
    language: str | None = None,
    warnings: RunContextWarningsInput = None,
) -> PreparedReportFacts:
    """Resolve semantic report facts shared by downstream PDF mapping."""
    origin = resolve_report_origin(test_run)
    origin_location = normalize_origin_location(origin)
    config_snap = test_run.capture.setup.configuration_snapshot
    context_facts = _build_report_context_facts(payload, summary=summary)
    sensor_facts = build_report_sensor_facts(
        test_run=test_run,
        sensor_locations_active=summary.active_sensor_locations,
        sensor_intensity=summary.sensor_intensity_rows,
    )
    decision_facts = build_report_decision_facts(
        payload,
        test_run=test_run,
        origin_location=origin_location,
        sensor_facts=sensor_facts,
        context_facts=context_facts,
        warnings=warnings,
    )
    evidence_facts = build_report_evidence_facts(
        payload,
        summary=summary,
        primary_candidate=decision_facts.primary_candidate,
        decision_facts=decision_facts,
    )
    sensor_facts = enrich_location_proof_sensor_facts(
        sensor_facts,
        primary_candidate=decision_facts.primary_candidate,
        evidence_data_basis=evidence_facts.data_basis,
    )
    confidence_facts = build_report_confidence_facts(
        has_explicit_analysis_metadata=isinstance(payload.get("analysis_metadata"), Mapping),
        primary_candidate=decision_facts.primary_candidate,
        evidence_facts=evidence_facts,
        decision_facts=decision_facts,
        context_facts=context_facts,
    )
    return PreparedReportFacts(
        run=ReportRunFacts(
            run_id=summary.run_id,
            origin=origin,
            origin_location=origin_location,
            report_date=summary.report_date,
            recorded_utc_offset_seconds=(
                summary.metadata.recorded_utc_offset_seconds
                if summary.metadata is not None
                else None
            ),
            duration_s=summary.duration_s,
            duration_text=summary.record_length,
            start_time_utc=summary.start_time_utc,
            end_time_utc=summary.end_time_utc,
            sample_rate_hz=(
                f"{config_snap.raw_sample_rate_hz:g}"
                if config_snap.raw_sample_rate_hz is not None
                else None
            ),
            tire_spec_text=_tire_spec_text(config_snap.tire_spec),
            sample_count=test_run.capture.sample_count,
            sensor_count=summary.sensor_count,
            sensor_model=config_snap.sensor_model,
            firmware_version=config_snap.firmware_version,
            car_name=summary.metadata.car_name if summary.metadata is not None else None,
            car_type=summary.metadata.car_type if summary.metadata is not None else None,
            timeline_intervals=summary.timeline_intervals,
            peak_table_rows=summary.peak_table_rows,
        ),
        context=context_facts,
        sensor=sensor_facts,
        decision=decision_facts,
        evidence=evidence_facts,
        confidence=confidence_facts,
        findings=prepare_report_findings(test_run),
    )


def _tire_spec_text(tire_spec: object) -> str | None:
    from vibesensor.domain import TireSpec

    if not isinstance(tire_spec, TireSpec):
        return None
    if tire_spec.width_mm <= 0 or tire_spec.aspect_pct <= 0 or tire_spec.rim_in <= 0:
        return None
    return f"{tire_spec.width_mm:g}/{tire_spec.aspect_pct:g}R{tire_spec.rim_in:g}"


def _build_report_context_facts(
    payload: Mapping[str, object],
    *,
    summary: NormalizedReportSummary,
) -> ReportContextFacts:
    analysis_metadata = payload.get("analysis_metadata")
    if not isinstance(analysis_metadata, Mapping):
        return ReportContextFacts(
            traceable=False,
            source="implicit",
            interval_count=0,
            intervals=(),
            window_count=None,
            full_window_count=0,
            partial_window_count=0,
            missing_window_count=0,
            missing_speed_window_count=0,
            missing_rpm_window_count=0,
            stale_speed_window_count=0,
            stale_rpm_window_count=0,
            warnings=(),
        )
    whole_run_available = bool(analysis_metadata.get("whole_run_context_available")) or bool(
        summary.whole_run_context_intervals
    )
    if whole_run_available:
        source = "whole_run"
    elif _is_summary_only_context_fallback(analysis_metadata):
        source = "summary_only"
    else:
        source = "legacy"
    intervals = summary.whole_run_context_intervals if whole_run_available else ()
    full_window_count = _analysis_metadata_count(
        analysis_metadata,
        "whole_run_context_full_window_count",
        default=sum(interval.full_context_window_count for interval in intervals),
    )
    partial_window_count = _analysis_metadata_count(
        analysis_metadata,
        "whole_run_context_partial_window_count",
        default=sum(interval.partial_context_window_count for interval in intervals),
    )
    missing_window_count = _analysis_metadata_count(
        analysis_metadata,
        "whole_run_context_missing_window_count",
        default=sum(interval.missing_context_window_count for interval in intervals),
    )
    missing_speed_window_count = _analysis_metadata_count(
        analysis_metadata,
        "whole_run_context_missing_speed_window_count",
    )
    missing_rpm_window_count = _analysis_metadata_count(
        analysis_metadata,
        "whole_run_context_missing_rpm_window_count",
    )
    stale_speed_window_count = _analysis_metadata_count(
        analysis_metadata,
        "whole_run_context_stale_speed_window_count",
    )
    stale_rpm_window_count = _analysis_metadata_count(
        analysis_metadata,
        "whole_run_context_stale_rpm_window_count",
    )
    default_window_count = (
        sum(interval.window_count for interval in intervals) if intervals else None
    )
    window_count = _analysis_metadata_optional_count(
        analysis_metadata,
        "whole_run_context_window_count",
        default=default_window_count,
    )
    interval_count = _analysis_metadata_count(
        analysis_metadata,
        "whole_run_context_interval_count",
        default=len(intervals),
    )
    return ReportContextFacts(
        traceable=True,
        source=source,
        interval_count=interval_count,
        intervals=intervals,
        window_count=window_count,
        full_window_count=full_window_count,
        partial_window_count=partial_window_count,
        missing_window_count=missing_window_count,
        missing_speed_window_count=missing_speed_window_count,
        missing_rpm_window_count=missing_rpm_window_count,
        stale_speed_window_count=stale_speed_window_count,
        stale_rpm_window_count=stale_rpm_window_count,
        warnings=_report_context_warnings(
            source=source,
            partial_window_count=partial_window_count,
            missing_window_count=missing_window_count,
            speed_gap_window_count=missing_speed_window_count + stale_speed_window_count,
            rpm_gap_window_count=missing_rpm_window_count + stale_rpm_window_count,
        ),
    )


def _is_summary_only_context_fallback(analysis_metadata: Mapping[str, object]) -> bool:
    raw_capture_mode = text_or_none(analysis_metadata.get("raw_capture_mode"))
    if raw_capture_mode == "summary_only":
        return True
    if raw_capture_mode == "raw_backed":
        return False
    return coerce_count(analysis_metadata.get("raw_backed_sample_count")) <= 0


def _analysis_metadata_count(
    analysis_metadata: Mapping[str, object],
    key: str,
    *,
    default: int = 0,
) -> int:
    return coerce_count(analysis_metadata.get(key)) if key in analysis_metadata else default


def _analysis_metadata_optional_count(
    analysis_metadata: Mapping[str, object],
    key: str,
    *,
    default: int | None,
) -> int | None:
    if key not in analysis_metadata:
        return default
    return coerce_count(analysis_metadata.get(key))


def _report_context_warnings(
    *,
    source: str,
    partial_window_count: int,
    missing_window_count: int,
    speed_gap_window_count: int,
    rpm_gap_window_count: int,
) -> tuple[RunContextWarning, ...]:
    if source == "legacy":
        return (
            RunContextWarning(
                code=WARNING_CODE_WHOLE_RUN_CONTEXT_LEGACY_FALLBACK,
                severity="warn",
                applies_to="report",
                title=i18n_ref("RUN_CONTEXT_WARNING_WHOLE_RUN_CONTEXT_LEGACY_TITLE"),
                detail=i18n_ref("RUN_CONTEXT_WARNING_WHOLE_RUN_CONTEXT_LEGACY_DETAIL"),
            ),
        )
    if source != "whole_run" or (partial_window_count <= 0 and missing_window_count <= 0):
        return ()
    return (
        RunContextWarning(
            code=WARNING_CODE_WHOLE_RUN_CONTEXT_INCOMPLETE,
            severity="warn",
            applies_to="report",
            title=i18n_ref("RUN_CONTEXT_WARNING_WHOLE_RUN_CONTEXT_INCOMPLETE_TITLE"),
            detail=i18n_ref(
                "RUN_CONTEXT_WARNING_WHOLE_RUN_CONTEXT_INCOMPLETE_DETAIL",
                partial_windows=str(max(0, partial_window_count)),
                missing_windows=str(max(0, missing_window_count)),
                speed_gap_windows=str(max(0, speed_gap_window_count)),
                rpm_gap_windows=str(max(0, rpm_gap_window_count)),
            ),
        ),
    )
