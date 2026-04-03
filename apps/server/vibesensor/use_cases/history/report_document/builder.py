"""Top-level report-document assembly orchestration."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.report_i18n import normalize_lang
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.reporting.contracts import PreparedReportInput
from vibesensor.shared.boundaries.reporting.document import (
    Report,
    ReportDocument,
    build_report_from_summary,
)
from vibesensor.shared.types.json_types import JsonValue
from vibesensor.use_cases.history.report_document.document_builder import (
    build_report_document_data,
)
from vibesensor.use_cases.history.report_document.resolved_sections import (
    resolve_report_document_sections,
)

__all__ = ["build_report_document"]


def build_report_document(prepared: PreparedReportInput) -> ReportDocument:
    """Build the canonical report document from prepared report input."""
    lang = str(normalize_lang(prepared.language))
    report = build_report_from_summary(
        prepared.summary,
        language=lang,
    )

    def tr(key: str, **kw: JsonValue) -> str:
        return str(_tr(lang, key, **kw))

    return _build_report_document(
        prepared,
        report=report,
        lang=lang,
        tr=tr,
    )


def _build_report_document(
    prepared: PreparedReportInput,
    *,
    report: Report,
    lang: str,
    tr: Callable[..., str],
) -> ReportDocument:
    """Resolve report sections, then assemble the canonical report document."""
    sections = resolve_report_document_sections(
        prepared,
        report=report,
        lang=lang,
        tr=tr,
    )

    return build_report_document_data(
        prepared=prepared,
        report=report,
        sections=sections,
    )
