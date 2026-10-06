"""PDF report delivery for stored history runs.

Framework-agnostic: raises domain exceptions from ``vibesensor.common.exceptions``
rather than HTTP-specific exceptions. The routes layer translates them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.common.exceptions import AnalysisNotReadyError
from vibesensor.common.filenames import safe_filename
from vibesensor.history.helpers import async_require_run, require_analysis_ready
from vibesensor.report.cache import HistoryReportPdfCache
from vibesensor.report.i18n import normalize_lang
from vibesensor.report.view_model import ReportView, build_report_view

if TYPE_CHECKING:
    from vibesensor.history.history_db import HistoryDB

__all__ = ["HistoryReportPdf", "HistoryReportService", "PdfRendererFn"]

#: Renders a report view to PDF bytes (injected so reportlab loads on first use).
type PdfRendererFn = Callable[[ReportView], bytes]


@dataclass(frozen=True)
class HistoryReportPdf:
    """Ready-to-send PDF download payload."""

    content: bytes
    filename: str


class HistoryReportService:
    """Build (and cache) the PDF report of one stored run."""

    __slots__ = ("_history_db", "_pdf_cache", "_pdf_renderer", "_speed_unit", "_time_zone")

    def __init__(
        self,
        history_db: HistoryDB,
        *,
        pdf_renderer: PdfRendererFn,
        time_zone: Callable[[], str | None] = lambda: None,
        speed_unit: Callable[[], str] = lambda: "kmh",
    ) -> None:
        self._history_db = history_db
        self._pdf_cache = HistoryReportPdfCache()
        self._pdf_renderer = pdf_renderer
        # The user's IANA zone (reported by the browser); run times render in it.
        self._time_zone = time_zone
        # The user's speed unit setting; speeds render in it, as on the History page.
        self._speed_unit = speed_unit

    async def build_pdf(self, run_id: str, requested_lang: str | None) -> HistoryReportPdf:
        """Render the run's report in the requested language (default: the run's)."""
        run = await async_require_run(self._history_db, run_id)
        analysis = require_analysis_ready(run)
        if "diagnosis" not in analysis.payload:
            raise AnalysisNotReadyError(
                "Report data unavailable for this run. Re-analyze to regenerate the PDF."
            )
        lang = normalize_lang(requested_lang or analysis.language or run.metadata.language)
        time_zone = self._time_zone()
        speed_unit = self._speed_unit()
        pdf = await self._pdf_cache.get_or_build(
            (run_id, lang, run.analysis_completed_at, time_zone, speed_unit),
            lambda: self._pdf_renderer(
                build_report_view(
                    analysis.payload,
                    run.metadata,
                    lang=lang,
                    time_zone=time_zone,
                    speed_unit=speed_unit,
                )
            ),
        )
        return HistoryReportPdf(content=pdf, filename=f"{safe_filename(run_id)}_report.pdf")
