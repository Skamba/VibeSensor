from __future__ import annotations

from io import BytesIO

import pytest
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.page1_header import draw_header_strip
from vibesensor.adapters.pdf.report_types import Page1RenderPlan
from vibesensor.shared.boundaries.reporting.document import VerdictPageData


def test_draw_header_strip_truncates_long_car_name_to_single_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_draw_text(
        c: Canvas,
        x: float,
        y_top: float,
        w: float,
        text: str,
        *,
        font: str,
        size: float,
        color: str,
        leading: float,
        max_lines: int | None = None,
    ) -> float:
        calls.append(
            {
                "text": text,
                "max_lines": max_lines,
            }
        )
        return y_top - leading

    monkeypatch.setattr("vibesensor.adapters.pdf.page1_header._draw_text", fake_draw_text)

    plan = Page1RenderPlan(
        title="VibeSensor Diagnostic Report",
        lang="en",
        run_datetime="2026-01-01 10:00 UTC",
        duration_text="12.3 s",
        car_name="A very long car name that would otherwise wrap into the next metadata row",
        car_type="Track Edition",
        sensor_count=4,
        sensor_locations=(),
        sensor_intensity_by_location=(),
        location_hotspot_rows=(),
        proof_sensor_intensity_by_location=(),
        proof_location_hotspot_rows=(),
        verdict_page=VerdictPageData(speed_window_label="60-90 km/h"),
        next_steps=(),
        findings=(),
        top_causes=(),
    )
    canvas = Canvas(BytesIO())

    draw_header_strip(
        canvas,
        plan,
        tr=lambda key, **_: key,
        x=10 * mm,
        y=10 * mm,
        w=180 * mm,
        h=24 * mm,
    )

    drawn_texts = [str(call["text"]) for call in calls]
    assert "12.3 s" in drawn_texts
    assert "60-90 km/h" in drawn_texts
    assert any(text.endswith("...") for text in drawn_texts)
    assert all(call["max_lines"] == 1 for call in calls)
