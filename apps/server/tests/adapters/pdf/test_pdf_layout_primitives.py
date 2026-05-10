from __future__ import annotations

from io import BytesIO

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from test_support.core import extract_pdf_text

from vibesensor.adapters.pdf.layout_primitives import (
    draw_overflow_note_if_room,
    draw_panel_region,
    draw_section_block_if_room,
)
from vibesensor.adapters.pdf.pdf_style import PAGE_SIZE


def test_pdf_layout_primitives_render_panel_section_and_overflow_note() -> None:
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=PAGE_SIZE, pageCompression=0)
    region = draw_panel_region(
        canvas,
        x=20 * mm,
        y=200 * mm,
        w=90 * mm,
        h=44 * mm,
        title="Primitive panel",
    )

    cursor, did_draw = draw_section_block_if_room(
        canvas,
        region=region,
        y=region.content_top,
        title="Evidence block",
        body="A compact body fits inside the reusable panel content region.",
        max_lines=2,
    )
    assert did_draw is True

    unchanged_cursor, did_draw = draw_section_block_if_room(
        canvas,
        region=region,
        y=region.content_bottom + 2 * mm,
        title="Hidden block",
        body="This body should not render because the cursor is already at the panel floor.",
        max_lines=2,
    )
    assert did_draw is False
    assert unchanged_cursor == region.content_bottom + 2 * mm

    draw_overflow_note_if_room(
        canvas,
        region=region,
        y=cursor,
        text="More evidence retained in source data.",
    )
    canvas.save()

    text = extract_pdf_text(buffer.getvalue())
    assert "Primitive panel" in text
    assert "Evidence block" in text
    assert "More evidence retained in source data." in text
    assert "Hidden block" not in text
