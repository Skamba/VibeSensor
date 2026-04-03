"""Explicit report-document assembly stage between preparation and rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from vibesensor.report_i18n import normalize_lang
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.reporting import PreparedReportInput
from vibesensor.shared.boundaries.reporting.document import Report, build_report_from_summary
from vibesensor.shared.types.json_types import JsonValue

from .resolved_sections import ResolvedReportDocumentSections, resolve_report_document_sections

__all__ = ["ReportDocumentAssembly", "assemble_report_document"]


@dataclass(frozen=True, slots=True)
class ReportDocumentAssembly:
    """Stable report assembly handoff before document-field mapping."""

    prepared: PreparedReportInput
    report: Report
    sections: ResolvedReportDocumentSections


def assemble_report_document(prepared: PreparedReportInput) -> ReportDocumentAssembly:
    """Resolve the canonical report aggregate and sections from prepared input."""
    lang = str(normalize_lang(prepared.language))
    report = build_report_from_summary(
        prepared.summary,
        language=lang,
    )

    def tr(key: str, **kw: JsonValue) -> str:
        return str(_tr(lang, key, **kw))

    return _assemble(prepared, report=report, lang=lang, tr=tr)


def _assemble(
    prepared: PreparedReportInput,
    *,
    report: Report,
    lang: str,
    tr: Callable[..., str],
) -> ReportDocumentAssembly:
    sections = resolve_report_document_sections(
        prepared,
        report=report,
        lang=lang,
        tr=tr,
    )
    return ReportDocumentAssembly(
        prepared=prepared,
        report=report,
        sections=sections,
    )
