"""History-side report preparation and prepared-input handoff."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from vibesensor.report_i18n import normalize_lang
from vibesensor.shared.boundaries.analysis_summary import analysis_summary_with_warnings
from vibesensor.shared.boundaries.analysis_payload import AnalysisSummary
from vibesensor.shared.boundaries.diagnostic_case import test_run_from_summary
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.history.helpers import safe_filename
from vibesensor.use_cases.history.report_cache import ReportPdfCacheKey

if TYPE_CHECKING:
    from vibesensor.domain import TestRun


def _has_projectable_analysis(analysis: AnalysisSummary) -> bool:
    return isinstance(analysis.get("findings"), list) or isinstance(
        analysis.get("top_causes"), list
    )


def _default_report_filename(summary: AnalysisSummary) -> str:
    run_id = str(summary.get("run_id") or summary.get("file_name") or "report")
    return f"{safe_filename(run_id)}_report.pdf"


@dataclass(frozen=True, slots=True)
class PreparedReportInput:
    """Resolved report input ready for PDF mapping and rendering.

    Invariants:
    - ``analysis_summary`` is a renderer-facing payload copy, not the
      authoritative internal report representation.
    - ``domain_test_run`` is reconstructed at most once and shared across the
      downstream PDF mapping helpers as the authoritative report aggregate.
    - ``language`` is canonicalized and copied back onto ``analysis_summary`` so
      renderer helpers consume one consistent locale choice.
    """

    analysis_summary: AnalysisSummary
    language: str
    filename: str
    domain_test_run: TestRun | None
    cache_key: ReportPdfCacheKey | None = None


def _reconstruct_report_test_run(analysis_summary: AnalysisSummary) -> TestRun | None:
    if not _has_projectable_analysis(analysis_summary):
        return None
    return test_run_from_summary(analysis_summary)


def _build_prepared_report_input(
    analysis_summary: AnalysisSummary,
    *,
    filename: str | None,
    language: str | None,
    cache_key: ReportPdfCacheKey | None,
) -> PreparedReportInput:
    domain_test_run = _reconstruct_report_test_run(analysis_summary)
    prepared_summary = cast(AnalysisSummary, dict(analysis_summary))
    prepared_language = str(normalize_lang(language or prepared_summary.get("lang")))
    prepared_summary["lang"] = prepared_language
    return PreparedReportInput(
        analysis_summary=prepared_summary,
        language=prepared_language,
        filename=filename or _default_report_filename(prepared_summary),
        domain_test_run=domain_test_run,
        cache_key=cache_key,
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
        cast(AnalysisSummary, dict(analysis_summary)),
        filename=filename,
        language=language,
        cache_key=cache_key,
    )

def prepare_persisted_report_input(
    analysis: PersistedAnalysis,
    *,
    warnings: object | None = None,
    filename: str | None = None,
    language: str | None = None,
    cache_key: ReportPdfCacheKey | None = None,
) -> PreparedReportInput:
    """Prepare a persisted history payload for domain-first report mapping."""
    prepared_summary = cast(AnalysisSummary, analysis.to_json_object())
    if warnings is not None:
        prepared_summary = analysis_summary_with_warnings(prepared_summary, warnings)
    return _build_prepared_report_input(
        prepared_summary,
        filename=filename,
        language=language,
        cache_key=cache_key,
    )
