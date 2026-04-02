"""PDF report build coordination for persisted history runs.

Framework-agnostic: raises domain exceptions from ``vibesensor.shared.exceptions``
rather than HTTP-specific exceptions.  The routes layer translates domain
exceptions to HTTP status codes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from vibesensor.shared.ports import RunPersistence
from vibesensor.use_cases.history.report_cache import HistoryReportPdfCache
from vibesensor.use_cases.history.report_loader import HistoryReportRequestLoader
from vibesensor.use_cases.history.report_preparation import (
    PreparedReportInput,
    prepare_persisted_report_input,
)

#: Callable that turns a prepared report input into PDF bytes.
PdfRendererFn = Callable[[PreparedReportInput], bytes]


@dataclass(frozen=True)
class HistoryReportPdf:
    """Ready-to-send PDF download payload."""

    content: bytes
    filename: str


class HistoryReportService:
    """Coordinate cached PDF generation for persisted history reports."""

    __slots__ = (
        "_loader",
        "_pdf_cache",
        "_pdf_renderer",
    )

    def __init__(
        self,
        history_db: RunPersistence,
        *,
        pdf_renderer: PdfRendererFn,
    ) -> None:
        self._loader = HistoryReportRequestLoader(history_db)
        self._pdf_cache = HistoryReportPdfCache()
        self._pdf_renderer = pdf_renderer

    async def build_pdf(self, run_id: str, requested_lang: str | None) -> HistoryReportPdf:
        request = await self._loader.load_report_request(run_id, requested_lang)
        cached_pdf = self._pdf_cache.get(request.cache_key)
        if cached_pdf is not None:
            return HistoryReportPdf(content=cached_pdf, filename=request.filename)

        pdf = await self._pdf_cache.get_or_build(
            request.cache_key,
            lambda: self._pdf_renderer(
                prepare_persisted_report_input(
                    request.analysis,
                    warnings=request.warnings,
                    filename=request.filename,
                    language=request.language,
                    cache_key=request.cache_key,
                )
            ),
        )
        return HistoryReportPdf(content=pdf, filename=request.filename)
