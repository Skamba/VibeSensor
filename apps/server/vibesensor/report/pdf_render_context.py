"""Render-time context for PDF page composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..report_i18n import tr as _tr
from .pdf_style import MARGIN, PAGE_H, PAGE_W
from .report_data import ReportTemplateData


@dataclass(frozen=True)
class PdfRenderContext:
    """Resolved page-rendering context derived from ReportTemplateData."""

    data: ReportTemplateData
    width: float
    page_top: float
    lang: str
    location_rows: list
    top_causes: list
    tr_fn: Callable[..., str]
    text_fn: Callable[[str, str], str]

    @classmethod
    def from_data(
        cls,
        data: ReportTemplateData,
        *,
        location_rows: list | None = None,
        top_causes: list | None = None,
        tr_fn: Callable[..., str] | None = None,
        text_fn: Callable[[str, str], str] | None = None,
    ) -> PdfRenderContext:
        lang = data.lang

        def default_tr(key: str, **kw: object) -> str:
            return _tr(lang, key, **kw)

        def default_text(en: str, nl: str) -> str:
            return nl if lang == "nl" else en

        return cls(
            data=data,
            width=PAGE_W - 2 * MARGIN,
            page_top=PAGE_H - MARGIN,
            lang=lang,
            location_rows=location_rows
            if location_rows is not None
            else data.location_hotspot_rows,
            top_causes=top_causes if top_causes is not None else data.top_causes,
            tr_fn=tr_fn or default_tr,
            text_fn=text_fn or default_text,
        )

    def tr(self, key: str, **kw: object) -> str:
        return self.tr_fn(key, **kw)
