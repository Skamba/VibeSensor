"""Stable PDF brand-color contracts for report chrome."""

from __future__ import annotations

from vibesensor.adapters.pdf.pdf_style import REPORT_COLORS


def test_pdf_brand_colors_align_with_website_palette() -> None:
    """PDF reports intentionally share the website's stable brand palette."""

    assert REPORT_COLORS["brand"] == "#7c3aed"
    assert REPORT_COLORS["brand_surface"] == "#ede9fe"
    assert REPORT_COLORS["brand_surface_soft"] == "#f4f0ff"
