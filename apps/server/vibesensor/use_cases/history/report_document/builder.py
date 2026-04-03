"""Canonical report-document builder from prepared report inputs."""

from __future__ import annotations

from dataclasses import replace

from vibesensor.report_i18n import normalize_lang
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.reporting import PreparedReportFacts, PreparedReportInput
from vibesensor.shared.boundaries.reporting.document import (
    NextStep,
    PatternEvidence,
    Report,
    ReportDocument,
    ReportDocumentContext,
    build_report_from_summary,
)
from vibesensor.shared.report_presentation import display_location
from vibesensor.shared.time_utils import (
    format_timestamp_in_recorded_timezone,
    format_utc_timestamp,
    utc_now_iso,
)
from vibesensor.shared.types.json_types import JsonValue

from ._candidate_resolver import PrimaryCandidateContext, resolve_primary_report_candidate
from ._card_builder import build_system_cards
from .composition import ReportDocumentComposition, compose_report_document
from .measurements import _measurement_rows
from .narrative_summaries import _proof_summary_text
from .pattern_evidence import build_pattern_evidence
from .peak_table import build_peak_rows
from .report_sections import build_data_trust, build_next_steps
from .sections import (
    _build_appendix_c_data,
    _build_appendix_d_data,
    _build_timeline_graph_data,
    _finding_to_presentation,
)

__all__ = ["ReportDocumentBuilder", "build_report_document", "build_report_document_data"]


class ReportDocumentBuilder:
    """Build the canonical report document through one immutable assembly context."""

    __slots__ = ("_lang", "_prepared")

    def __init__(self, prepared: PreparedReportInput) -> None:
        self._prepared = prepared
        self._lang = str(normalize_lang(prepared.language))

    def build(self) -> ReportDocument:
        report = build_report_from_summary(
            self._prepared.summary,
            language=self._lang,
        )
        context = self._build_context(report)
        return build_report_document_data(context)

    def _build_context(self, report: Report) -> ReportDocumentContext:
        prepared = self._prepared
        test_run = prepared.domain_test_run
        report_facts = prepared.report_facts
        tr = self._tr
        composition = compose_report_document(
            aggregate=test_run,
            report_facts=report_facts,
            lang=self._lang,
        )
        primary = resolve_primary_report_candidate(
            aggregate=test_run,
            facts=report_facts.primary_candidate_facts,
            tr=tr,
            lang=self._lang,
        )
        observed = self._observed_signature(primary)
        observed.strongest_location = display_location(primary.primary_location, tr=tr)
        data_trust = tuple(
            build_data_trust(
                suitability_checks=report_facts.suitability_checks,
                warnings=report_facts.warnings,
                lang=self._lang,
                tr=tr,
            )
        )
        pattern_evidence = build_pattern_evidence(
            aggregate=test_run,
            origin=report_facts.origin,
            primary=primary,
            lang=self._lang,
            tr=tr,
        )
        findings = tuple(_finding_to_presentation(finding) for finding in test_run.findings)
        peak_rows = tuple(
            build_peak_rows(
                prepared.summary.peak_table_rows,
                findings=list(findings),
                lang=self._lang,
                tr=tr,
            )
        )
        proof_summary = _proof_summary_text(
            test_run,
            primary,
            report_facts,
            composition,
            tr=tr,
        )
        return ReportDocumentContext(
            title=tr("REPORT_FOOTER_TITLE"),
            run_datetime=self._report_date_text(prepared),
            run_id=report.run_id,
            duration_text=report_facts.duration_text,
            start_time_utc=format_utc_timestamp(report_facts.start_time_utc),
            end_time_utc=format_utc_timestamp(report_facts.end_time_utc),
            sample_rate_hz=report_facts.sample_rate_hz,
            tire_spec_text=report_facts.tire_spec_text,
            sample_count=report_facts.sample_count,
            sensor_count=primary.sensor_count,
            sensor_locations=tuple(report_facts.sensor_locations_active),
            sensor_model=report_facts.sensor_model,
            firmware_version=report_facts.firmware_version,
            car_name=report.car_name
            or (
                prepared.summary.metadata.car_name
                if prepared.summary.metadata is not None
                else None
            ),
            car_type=report.car_type
            or (
                prepared.summary.metadata.car_type
                if prepared.summary.metadata is not None
                else None
            ),
            observed=observed,
            system_cards=tuple(
                build_system_cards(
                    test_run,
                    primary,
                    self._lang,
                    tr,
                )
            ),
            next_steps=self._resolve_next_steps(
                primary=primary,
                report_facts=report_facts,
                composition=composition,
            ),
            data_trust=data_trust,
            pattern_evidence=pattern_evidence,
            peak_rows=peak_rows,
            language=self._lang,
            certainty_tier_key=primary.tier,
            findings=findings,
            top_causes=tuple(
                _finding_to_presentation(finding) for finding in test_run.effective_top_causes()
            ),
            sensor_intensity_by_location=tuple(report_facts.active_sensor_intensity),
            location_hotspot_rows=tuple(report_facts.location_hotspot_rows),
            verdict_page=replace(
                composition.verdict_page,
                proof_summary=proof_summary,
                timeline_graph=_build_timeline_graph_data(
                    report_facts,
                    duration_s=report.duration_s,
                ),
            ),
            appendix_a=composition.appendix_a,
            appendix_b=composition.appendix_b,
            appendix_c=_build_appendix_c_data(
                primary=primary,
                aggregate=test_run,
                measurements=_measurement_rows(
                    prepared.summary,
                    aggregate=test_run,
                    tr=tr,
                ),
                report_facts=report_facts,
                composition=composition,
                data_trust=list(data_trust),
                tr=tr,
            ),
            appendix_d=_build_appendix_d_data(
                date_str=self._report_date_text(prepared),
                run_id=report.run_id,
                tire_spec_text=report_facts.tire_spec_text,
                sensor_model=report_facts.sensor_model,
                firmware_version=report_facts.firmware_version,
                sample_count=report_facts.sample_count,
                sample_rate_hz=report_facts.sample_rate_hz,
                tr=tr,
            ),
        )

    def _resolve_next_steps(
        self,
        *,
        primary: PrimaryCandidateContext,
        report_facts: PreparedReportFacts,
        composition: ReportDocumentComposition,
    ) -> tuple[NextStep, ...]:
        recapture_mode = report_facts.action_status_key == "recapture_before_acting"
        if recapture_mode:
            return tuple(
                NextStep(action=action) for action in composition.appendix_a.capture_changes
            )
        return tuple(
            build_next_steps(
                recommended_actions=report_facts.recommended_actions,
                primary_source=primary.primary_source,
                primary_location=primary.primary_location,
                tier=primary.tier,
                cert_reason=primary.certainty_reason or self._tr("REPORT_CAPTURE_ISSUE_GENERIC"),
                recapture_mode=recapture_mode,
                lang=self._lang,
                tr=self._tr,
            )
        )

    def _observed_signature(self, primary: PrimaryCandidateContext) -> PatternEvidence:
        return PatternEvidence(
            primary_system=primary.primary_system,
            strongest_location=primary.primary_location,
            speed_band=primary.primary_speed,
            strength_label=primary.strength_text,
            strength_peak_db=primary.strength_db,
            certainty_label=primary.certainty_label_text,
            certainty_pct=primary.certainty_pct,
            certainty_reason=primary.certainty_reason,
        )

    def _report_date_text(self, prepared: PreparedReportInput) -> str:
        report_date = prepared.summary.report_date or utc_now_iso()
        recorded_offset_seconds = (
            prepared.summary.metadata.recorded_utc_offset_seconds
            if prepared.summary.metadata is not None
            else None
        )
        return format_timestamp_in_recorded_timezone(
            report_date,
            recorded_offset_seconds,
        ) or str(report_date)

    def _tr(self, key: str, **kw: JsonValue) -> str:
        return str(_tr(self._lang, key, **kw))


def build_report_document_data(context: ReportDocumentContext) -> ReportDocument:
    """Map one canonical build context into the adapter-facing report document."""

    return ReportDocument(
        title=context.title,
        run_datetime=context.run_datetime,
        run_id=context.run_id,
        duration_text=context.duration_text,
        start_time_utc=context.start_time_utc,
        end_time_utc=context.end_time_utc,
        sample_rate_hz=context.sample_rate_hz,
        tire_spec_text=context.tire_spec_text,
        sample_count=context.sample_count,
        sensor_count=context.sensor_count,
        sensor_locations=list(context.sensor_locations),
        sensor_model=context.sensor_model,
        firmware_version=context.firmware_version,
        car_name=context.car_name,
        car_type=context.car_type,
        observed=context.observed,
        system_cards=list(context.system_cards),
        next_steps=list(context.next_steps),
        data_trust=list(context.data_trust),
        pattern_evidence=context.pattern_evidence,
        peak_rows=list(context.peak_rows),
        lang=context.language,
        certainty_tier_key=context.certainty_tier_key,
        findings=list(context.findings),
        top_causes=list(context.top_causes),
        sensor_intensity_by_location=list(context.sensor_intensity_by_location),
        location_hotspot_rows=list(context.location_hotspot_rows),
        verdict_page=context.verdict_page,
        appendix_a=context.appendix_a,
        appendix_b=context.appendix_b,
        appendix_c=context.appendix_c,
        appendix_d=context.appendix_d,
    )


def build_report_document(prepared: PreparedReportInput) -> ReportDocument:
    """Build the canonical report document from prepared report input."""

    return ReportDocumentBuilder(prepared).build()
