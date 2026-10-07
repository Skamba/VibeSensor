"""Render the report of an analysis summary for tests (view model and PDF text)."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import cast

from vibesensor.recording.run_metadata import run_metadata_from_mapping
from vibesensor.report.pdf import render_report_pdf
from vibesensor.report.view_model import ReportView, build_report_view
from vibesensor.summary.contracts import AnalysisSummary


def report_view_for(
    summary: Mapping[str, object], *, lang: str = "en", speed_unit: str = "kmh"
) -> ReportView:
    """Report view of *summary*, with run metadata taken from the summary's own metadata."""
    metadata = summary.get("metadata")
    metadata_map = dict(metadata) if isinstance(metadata, Mapping) else {}
    metadata_map.setdefault("run_id", summary.get("run_id") or "run")
    return build_report_view(
        cast(AnalysisSummary, summary),
        run_metadata_from_mapping(metadata_map),
        lang=lang,
        speed_unit=speed_unit,
    )


def report_pdf_for(summary: Mapping[str, object], *, lang: str = "en") -> bytes:
    return render_report_pdf(report_view_for(summary, lang=lang))


# Parts a front-wheel-drive car does not have, in English and Dutch.
PROPSHAFT_WORDS = (
    "propshaft",
    "center bearing",
    "u-joint",
    "rear differential",
    "cardanas",
    "middenlager",
    "kruiskoppeling",
    "achterdifferentieel",
)


def report_view_texts(view: object) -> list[str]:
    """Every string a report view (or any part of it) shows."""
    if isinstance(view, str):
        return [view]
    if dataclasses.is_dataclass(view) and not isinstance(view, type):
        return [
            text
            for item in dataclasses.fields(view)
            for text in report_view_texts(getattr(view, item.name))
        ]
    if isinstance(view, tuple | list):
        return [text for item in view for text in report_view_texts(item)]
    return []


def propshaft_mentions(texts: list[str]) -> list[str]:
    """The texts that name a propshaft or rear-axle drive part."""
    return [text for text in texts if any(word in text.lower() for word in PROPSHAFT_WORDS)]


# Driveline parts that turn at wheel speed (a fault there shows at the wheel
# order), so a driveline-order (P1/P2) fault never points to them.
WHEEL_SPEED_PART_WORDS = (
    "drive shaft",
    "cv joint",
    "intermediate shaft",
    "aandrijfas",
    "homokinet",
    "tussenas",
)


def wheel_speed_part_mentions(texts: list[str]) -> list[str]:
    """The texts that name a drive shaft or CV joint."""
    return [text for text in texts if any(word in text.lower() for word in WHEEL_SPEED_PART_WORDS)]
