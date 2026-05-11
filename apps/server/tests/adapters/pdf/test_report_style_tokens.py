"""Stable PDF style-token contracts for report chrome branding."""

from __future__ import annotations

from vibesensor.adapters.pdf.pdf_style import (
    FS_CARD_TITLE,
    FS_H2,
    FS_TITLE,
    R_CARD,
    REPORT_COLORS,
)


def test_pdf_theme_tokens_align_with_website_palette() -> None:
    """PDF reports intentionally share the website's stable brand palette."""

    assert REPORT_COLORS["brand"] == "#7c3aed"
    assert REPORT_COLORS["brand_surface"] == "#ede9fe"
    assert REPORT_COLORS["warning"] == "#b7791f"
    assert REPORT_COLORS["ink"] == "#1a1c24"
    assert REPORT_COLORS["text_primary"] == "#1a1c24"
    assert REPORT_COLORS["ink"] == REPORT_COLORS["text_primary"]
    assert REPORT_COLORS["surface"] == "#f8f9fb"


def test_pdf_typography_and_radius_shift_toward_website_chrome() -> None:
    """PDF report chrome keeps compact type and card radius as a design contract."""

    assert FS_TITLE == 13
    assert FS_H2 == 10
    assert FS_CARD_TITLE == 9.0
    assert R_CARD == 8
