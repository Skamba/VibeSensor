"""History-side report preparation and mapping-ready handoff."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from vibesensor.report_i18n import normalize_lang
from vibesensor.shared.boundaries.reporting import PreparedReportInput
from vibesensor.shared.boundaries.reporting.payload import (
    report_summary_from_mapping,
    require_projectable_report_payload,
)
from vibesensor.shared.boundaries.test_run_reconstruction import (
    test_run_from_persisted_analysis,
    test_run_from_summary,
)
from vibesensor.shared.run_context_warning import RunContextWarningsInput
from vibesensor.shared.types.history_analysis_contracts import (
    AnalysisSummary,
)
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.report_cache import ReportPdfCacheKey
from vibesensor.use_cases.history.helpers import safe_filename
from vibesensor.use_cases.history.report_facts import prepare_report_facts
from vibesensor.use_cases.history.report_presentation import prepare_report_presentation

if TYPE_CHECKING:
    from vibesensor.domain import TestRun

__all__ = [
    "prepare_persisted_report_input",
    "prepare_report_input",
]


def _default_report_filename(payload: Mapping[str, object]) -> str:
    """Derive the default PDF filename from stable report-identifying payload fields."""
    run_id = str(payload.get("run_id") or payload.get("file_name") or "report")
    return f"{safe_filename(run_id)}_report.pdf"


def _reconstruct_report_test_run(payload: Mapping[str, object]) -> TestRun:
    """Rebuild the report domain aggregate from one canonical projectable payload."""
    require_projectable_report_payload(payload)
    return test_run_from_summary(payload)


def _build_prepared_report_input(
    payload: Mapping[str, object],
    *,
    domain_test_run: TestRun,
    filename: str | None,
    language: str | None,
    cache_key: ReportPdfCacheKey | None,
    warnings: RunContextWarningsInput = None,
) -> PreparedReportInput:
    """Assemble the canonical report handoff for downstream PDF rendering."""
    prepared_language = str(normalize_lang(language or payload.get("lang")))
    summary = report_summary_from_mapping(payload)
    report_facts = prepare_report_facts(
        payload,
        summary=summary,
        test_run=domain_test_run,
        language=prepared_language,
        warnings=warnings,
    )
    presentation = prepare_report_presentation(
        aggregate=domain_test_run,
        report_facts=report_facts,
        lang=prepared_language,
    )
    return PreparedReportInput(
        summary=summary,
        language=prepared_language,
        filename=filename or _default_report_filename(payload),
        domain_test_run=domain_test_run,
        cache_key=cache_key,
        report_facts=report_facts,
        presentation=presentation,
    )


def prepare_report_input(
    analysis_summary: AnalysisSummary,
    *,
    filename: str | None = None,
    language: str | None = None,
    cache_key: ReportPdfCacheKey | None = None,
) -> PreparedReportInput:
    """Prepare a direct summary payload for domain-first report mapping."""
    return _build_prepared_report_input(
        analysis_summary,
        domain_test_run=_reconstruct_report_test_run(analysis_summary),
        filename=filename,
        language=language,
        cache_key=cache_key,
    )


def prepare_persisted_report_input(
    analysis: PersistedAnalysis,
    *,
    warnings: RunContextWarningsInput = None,
    filename: str | None = None,
    language: str | None = None,
    cache_key: ReportPdfCacheKey | None = None,
) -> PreparedReportInput:
    """Prepare a persisted history payload for domain-first report mapping."""
    require_projectable_report_payload(analysis)
    return _build_prepared_report_input(
        analysis,
        domain_test_run=test_run_from_persisted_analysis(analysis),
        filename=filename,
        language=language,
        cache_key=cache_key,
        warnings=warnings,
    )
