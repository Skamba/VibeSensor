"""Report rendering regressions."""

from __future__ import annotations

import inspect
import json
from io import BytesIO

import pytest
from _paths import SERVER_ROOT
from reportlab.pdfgen.canvas import Canvas

from vibesensor.report import pdf_page1
from vibesensor.report.pdf_page1 import _draw_next_steps_table, _draw_system_card
from vibesensor.report.pdf_page2 import _page2
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

    def test_page2_passes_start_number(self) -> None:
        src = inspect.getsource(_page2)
        assert "start_number=" in src, "_page2 must pass start_number to _draw_next_steps_table"


class TestSystemCardTone:
    """Regression: _draw_system_card must use card.tone for colors."""

    def test_tone_used_in_draw_system_card(self) -> None:
        src = inspect.getsource(_draw_system_card)
        assert "card.tone" in src, "Must reference card.tone"
        assert "card_neutral_bg" in src or "card_{card.tone}" in src, (
            "Must look up tone-specific theme colors"
        )


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
                )
            ],
        )

        assert len(captured) == 1
        assert "verify looseness" in captured[0]
        assert "movement increases" in captured[0]
        assert "mount remains rigid" in captured[0]
        assert "15 min" in captured[0]


def _make_processing_config(**overrides):
    """Create ProcessingConfig with sensible defaults, overriding as needed."""
    from vibesensor.config import ProcessingConfig

    defaults = {
        "sample_rate_hz": 800,
        "waveform_seconds": 8,
        "waveform_display_hz": 100,
        "ui_push_hz": 10,
        "ui_heavy_push_hz": 4,
        "fft_update_hz": 4,
        "fft_n": 2048,
        "spectrum_min_hz": 5.0,
        "spectrum_max_hz": 200,
        "client_ttl_seconds": 10,
        "accel_scale_g_per_lsb": None,
    }
    defaults.update(overrides)
    return ProcessingConfig(**defaults)


class TestFftNUpperBound:
    """Regression: fft_n must be clamped to a max of 65536."""

    @pytest.mark.parametrize(
        ("fft_n", "expected"),
        [
            pytest.param(2**20, 65536, id="absurd_clamped"),
            pytest.param(4096, 4096, id="normal_unchanged"),
            pytest.param(65536, 65536, id="max_boundary"),
        ],
    )
    def test_fft_n_clamping(self, fft_n: int, expected: int) -> None:
        cfg = _make_processing_config(fft_n=fft_n)
        assert cfg.fft_n == expected


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


class TestNoGlobalRandomSeed:
    """Regression: test files must not use global random.seed()."""

    def test_i18n_separation_no_global_seed(self) -> None:
        import tests.report.test_i18n_separation as mod

        src = inspect.getsource(mod)
        assert "random.seed(" not in src, "Must use random.Random(seed) instead of random.seed()"


class TestNoMutableClassDefault:
    """Regression: _FakeRecord must not use mutable class-level default."""

    def test_shutdown_analysis_fake_record(self) -> None:
        import tests.analysis.test_shutdown_analysis as mod

        src = inspect.getsource(mod)
        assert "latest_metrics: dict = {}" not in src, (
            "Must use __init__ or field(default_factory=dict)"
        )
