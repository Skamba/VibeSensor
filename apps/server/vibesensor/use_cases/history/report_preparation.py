"""History-side report preparation and prepared-input handoff."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from vibesensor.report_i18n import normalize_lang
from vibesensor.shared.boundaries.analysis_payload import AnalysisSummary
from vibesensor.shared.boundaries.analysis_summary_projection import project_analysis_summary
from vibesensor.shared.types.json_types import JsonObject
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
    - ``analysis_summary`` has already gone through the canonical history-side
      projection/reconstruction pass when the payload is projectable.
    - ``domain_test_run`` is reconstructed at most once and shared across the
      downstream PDF mapping helpers.
    - ``language`` is canonicalized and copied back onto ``analysis_summary`` so
      renderer helpers consume one consistent locale choice.
    """

    analysis_summary: AnalysisSummary
    language: str
    filename: str
    domain_test_run: TestRun | None
    cache_key: ReportPdfCacheKey | None = None


def prepare_report_input(
    analysis_summary: AnalysisSummary,
    *,
    filename: str | None = None,
    language: str | None = None,
    cache_key: ReportPdfCacheKey | None = None,
) -> PreparedReportInput:
    """Project persisted report analysis once and return the typed handoff object."""
    if _has_projectable_analysis(analysis_summary):
        projected, domain_test_run = project_analysis_summary(
            cast(JsonObject, dict(analysis_summary))
        )
        prepared_summary = cast(AnalysisSummary, projected)
    else:
        prepared_summary = cast(AnalysisSummary, dict(analysis_summary))
        domain_test_run = None

    prepared_language = str(normalize_lang(language or prepared_summary.get("lang")))
    prepared_summary["lang"] = prepared_language

    return PreparedReportInput(
        analysis_summary=prepared_summary,
        language=prepared_language,
        filename=filename or _default_report_filename(prepared_summary),
        domain_test_run=domain_test_run,
        cache_key=cache_key,
    )
