"""Report rendering regressions."""

from __future__ import annotations

import json
from io import BytesIO

import pytest
from _paths import SERVER_ROOT
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

import vibesensor.adapters.pdf.panels._panel_header as panel_header
import vibesensor.adapters.pdf.panels._panel_trust_steps as panel_trust_steps
from vibesensor.adapters.pdf.panels._panel_trust_steps import _draw_next_steps_table
from vibesensor.adapters.pdf.pdf_style import FONT, FS_H2, PdfRenderContext
from vibesensor.adapters.pdf.report_data import NextStep, PatternEvidence, ReportTemplateData
from vibesensor.report_i18n import tr as report_tr


def _make_canvas() -> Canvas:
    return Canvas(BytesIO())


class TestNextStepNumberingContinuation:
    """Regression: next-step numbering must continue from page 1 count."""

    def test_draw_next_steps_table_starts_from_requested_number(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        canvas = _make_canvas()
        labels: list[str] = []
        original_draw_string = canvas.drawString

        def capture_label(x: float, y: float, text: str, *args, **kwargs):
            labels.append(text)
            return original_draw_string(x, y, text, *args, **kwargs)

        monkeypatch.setattr(canvas, "drawString", capture_label)
        drawn = _draw_next_steps_table(
            canvas,
            0,
            220,
            180,
            0,
            [NextStep(action="Inspect wheel bearing")],
            start_number=5,
            tr=lambda key: key,
        )

        assert drawn == 1
        assert "5." in labels


class TestNextStepFieldsRendered:
    """Regression: action renders separately from compact why/confirm/eta details."""

    def test_optional_fields_are_included_in_rendered_text(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: list[str] = []

        def capture_text(*args, **kwargs) -> float:
            captured.append(args[4])
            return float(args[2]) - 10.0

        monkeypatch.setattr(panel_trust_steps, "_draw_text", capture_text)
        _draw_next_steps_table(
            _make_canvas(),
            0,
            220,
            180,
            0,
            [
                NextStep(
                    action="Inspect mount",
                    why="verify looseness",
                    confirm="movement increases",
                    falsify="mount remains rigid",
                    eta="15 min",
                ),
            ],
            tr=lambda key: {"WHY": "Why", "CONFIRM": "Confirm", "ETA": "ETA"}[key],
        )

        assert len(captured) == 2
        assert captured[0] == "Inspect mount"
        assert "Why: verify looseness" in captured[1]
        assert "Confirm: movement increases" in captured[1]
        assert "ETA: 15 min" in captured[1]
        assert "mount remains rigid" not in captured[1]


class TestNextStepCardPadding:
    """Regression: next-step row content should not crowd the row border."""

    def test_first_row_uses_comfortable_top_and_left_insets(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        canvas = _make_canvas()
        rect_calls: list[tuple[float, float, float, float]] = []
        draw_calls: list[tuple[float, float, str]] = []
        original_rect = canvas.rect
        original_draw_string = canvas.drawString

        def capture_rect(x: float, y: float, w: float, h: float, *args, **kwargs):
            rect_calls.append((float(x), float(y), float(w), float(h)))
            return original_rect(x, y, w, h, *args, **kwargs)

        def capture_draw_string(x: float, y: float, text: str, *args, **kwargs):
            draw_calls.append((float(x), float(y), str(text)))
            return original_draw_string(x, y, text, *args, **kwargs)

        monkeypatch.setattr(canvas, "rect", capture_rect)
        monkeypatch.setattr(canvas, "drawString", capture_draw_string)

        drawn = _draw_next_steps_table(
            canvas,
            20.0,
            220.0,
            180.0,
            0.0,
            [
                NextStep(
                    action=(
                        "Inspect the rear-right wheel bearing preload and confirm "
                        "whether the vibration changes with steering input"
                    ),
                    why="reproduce the strongest signature under the same load window",
                    confirm="tone and vibration strength drop after the adjustment",
                    eta="15 min",
                ),
            ],
            tr=lambda key: {"WHY": "Why", "CONFIRM": "Confirm", "ETA": "ETA"}[key],
        )

        assert drawn == 1
        row_x, row_y, _row_w, row_h = rect_calls[0]
        row_top = row_y + row_h

        number_x, _number_y, _number_text = next(
            (x, y, text) for x, y, text in draw_calls if text == "1."
        )
        action_x, action_y, action_text = next(
            (x, y, text) for x, y, text in draw_calls if text.startswith("Inspect the")
        )
        detail_x, _detail_y, detail_text = next(
            (x, y, text) for x, y, text in draw_calls if text.startswith("Why:")
        )

        assert action_text
        assert detail_text
        assert number_x - row_x >= 1.8 * mm
        assert detail_x == action_x
        assert row_top - action_y >= 2.5 * mm


class TestOrphanI18nKeysRemoved:
    """Regression: orphan g-unit i18n keys must not exist."""

    ORPHAN_KEYS = [
        "AMP_G",
        "MAX_AMPLITUDE_G",
        "MEAN_AMPLITUDE_G",
        "MEAN_G",
        "PEAK_AMPLITUDE_G",
        "PEAK_AMP_G",
        "PLOT_Y_MEAN_AMPLITUDE_G",
    ]

    def test_orphan_keys_absent(self) -> None:
        i18n_path = SERVER_ROOT / "data" / "report_i18n.json"
        data = json.loads(i18n_path.read_text())
        for key in self.ORPHAN_KEYS:
            assert key not in data, f"Orphan key {key!r} should have been removed"


class TestObservedSignatureLayout:
    """Regression: long observed-signature values must not start inside the label."""

    def test_check_first_value_starts_after_rendered_label_width(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        canvas = _make_canvas()
        draw_calls: list[tuple[float, float, str]] = []
        original_draw_string = canvas.drawString

        def capture_draw_string(x: float, y: float, text: str, *args, **kwargs):
            draw_calls.append((float(x), float(y), str(text)))
            return original_draw_string(x, y, text, *args, **kwargs)

        monkeypatch.setattr(canvas, "drawString", capture_draw_string)

        data = ReportTemplateData(
            observed=PatternEvidence(
                primary_system="Wheel / Tire",
                strongest_location="Rear-Right / Front-Left",
                speed_band="50-60 km/h",
                strength_label="Moderate",
                certainty_label="High",
            ),
            lang="en",
            certainty_tier_key="C",
        )
        render_ctx = PdfRenderContext.from_data(data)

        def tr(key: str) -> str:
            return report_tr("en", key)

        y_cursor = panel_header._draw_header_panel(
            canvas,
            data,
            tr=tr,
            width=render_ctx.width,
            page_top=render_ctx.page_top,
            na=tr("UNKNOWN"),
        )
        panel_header._draw_observed_signature_panel(
            canvas,
            data,
            tr=tr,
            width=render_ctx.width,
            y_cursor=y_cursor,
            na=tr("UNKNOWN"),
        )

        label_text = f"{tr('WHAT_TO_CHECK_FIRST')}:"
        label_index = next(
            index for index, (_x, _y, text) in enumerate(draw_calls) if text == label_text
        )
        label_x, _label_y, _ = draw_calls[label_index]
        value_x, _value_y, value_text = next(
            (x, y, text) for x, y, text in draw_calls[label_index + 1 :] if "Rear-Right" in text
        )
        label_end_x = label_x + canvas.stringWidth(label_text, FONT, FS_H2)

        assert value_text
        assert value_x >= label_end_x + (0.8 * mm)
