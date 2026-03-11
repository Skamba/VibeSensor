"""Report rendering regressions."""

from __future__ import annotations

import json
from io import BytesIO

import pytest
from _paths import SERVER_ROOT
from reportlab.pdfgen.canvas import Canvas

from vibesensor.report import pdf_page1
from vibesensor.report.pdf_page1 import _draw_next_steps_table
from vibesensor.report.report_data import NextStep


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
        )

        assert drawn == 1
        assert "5." in labels


class TestNextStepFieldsRendered:
    """Regression: confirm/falsify/eta must appear in rendered text."""

    def test_optional_fields_are_included_in_rendered_text(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: list[str] = []

        def capture_text(*args, **kwargs) -> None:
            captured.append(args[4])

        monkeypatch.setattr(pdf_page1, "_draw_text", capture_text)
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
        )

        assert len(captured) == 1
        assert "verify looseness" in captured[0]
        assert "movement increases" in captured[0]
        assert "mount remains rigid" in captured[0]
        assert "15 min" in captured[0]


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
