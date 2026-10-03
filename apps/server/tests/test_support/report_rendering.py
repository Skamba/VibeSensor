"""Render the report of an analysis summary for tests (view model and PDF text)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from test_support.pdf import extract_pdf_text
from vibesensor.recording.run_metadata import run_metadata_from_mapping
from vibesensor.report.pdf import render_report_pdf
from vibesensor.report.view_model import ReportView, build_report_view
from vibesensor.summary.contracts import AnalysisSummary


def report_view_for(summary: Mapping[str, object], *, lang: str = "en") -> ReportView:
    """Report view of *summary*, with run metadata taken from the summary's own metadata."""
    metadata = summary.get("metadata")
    metadata_map = dict(metadata) if isinstance(metadata, Mapping) else {}
    metadata_map.setdefault("run_id", summary.get("run_id") or "run")
    return build_report_view(
        cast(AnalysisSummary, summary),
        run_metadata_from_mapping(metadata_map),
        lang=lang,
    )


def report_pdf_for(summary: Mapping[str, object], *, lang: str = "en") -> bytes:
    return render_report_pdf(report_view_for(summary, lang=lang))


def report_pdf_text(summary: Mapping[str, object], *, lang: str = "en") -> str:
    return extract_pdf_text(report_pdf_for(summary, lang=lang))
