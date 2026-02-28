"""Tests for Cycle 4b fixes:
- Next-step numbering continues across pages (start_number param)
- SystemFindingCard.tone wired to theme colors
- NextStep confirm/falsify/eta rendered
- fft_n upper bound clamped at 65536
- Orphan g-unit i18n keys removed
- Test quality: no global random.seed, no mutable class-level dict
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path


class TestNextStepNumberingContinuation:
    """Regression: next-step numbering must continue from page 1 count."""

    def test_draw_next_steps_table_accepts_start_number(self) -> None:
        from vibesensor.report.pdf_builder import _draw_next_steps_table

        sig = inspect.signature(_draw_next_steps_table)
        assert "start_number" in sig.parameters, (
            "_draw_next_steps_table must accept start_number kwarg"
        )

    def test_page2_passes_start_number(self) -> None:
        from vibesensor.report.pdf_builder import _page2

        src = inspect.getsource(_page2)
        assert "start_number=" in src, (
            "_page2 must pass start_number to _draw_next_steps_table"
        )


class TestSystemCardTone:
    """Regression: _draw_system_card must use card.tone for colors."""

    def test_tone_used_in_draw_system_card(self) -> None:
        from vibesensor.report.pdf_builder import _draw_system_card

        src = inspect.getsource(_draw_system_card)
        assert "card.tone" in src, "Must reference card.tone"
        assert "card_neutral_bg" in src or "card_{card.tone}" in src, (
            "Must look up tone-specific theme colors"
        )


class TestNextStepFieldsRendered:
    """Regression: confirm/falsify/eta must appear in rendered text."""

    def test_confirm_rendered(self) -> None:
        from vibesensor.report.pdf_builder import _draw_next_steps_table

        src = inspect.getsource(_draw_next_steps_table)
        assert "step.confirm" in src, "confirm field must be checked"

    def test_falsify_rendered(self) -> None:
        from vibesensor.report.pdf_builder import _draw_next_steps_table

        src = inspect.getsource(_draw_next_steps_table)
        assert "step.falsify" in src, "falsify field must be checked"

    def test_eta_rendered(self) -> None:
        from vibesensor.report.pdf_builder import _draw_next_steps_table

        src = inspect.getsource(_draw_next_steps_table)
        assert "step.eta" in src, "eta field must be checked"


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

    def test_absurd_fft_n_clamped(self) -> None:
        cfg = _make_processing_config(fft_n=2**20)
        assert cfg.fft_n <= 65536, (
            f"fft_n should be clamped but got {cfg.fft_n}"
        )

    def test_normal_fft_n_unchanged(self) -> None:
        cfg = _make_processing_config(fft_n=4096)
        assert cfg.fft_n == 4096

    def test_max_boundary(self) -> None:
        cfg = _make_processing_config(fft_n=65536)
        assert cfg.fft_n == 65536


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
        i18n_path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "report_i18n.json"
        )
        data = json.loads(i18n_path.read_text())
        for key in self.ORPHAN_KEYS:
            assert key not in data, (
                f"Orphan key {key!r} should have been removed"
            )


class TestNoGlobalRandomSeed:
    """Regression: test files must not use global random.seed()."""

    def test_i18n_separation_no_global_seed(self) -> None:
        import tests.test_i18n_separation as mod

        src = inspect.getsource(mod)
        assert "random.seed(" not in src, (
            "Must use random.Random(seed) instead of random.seed()"
        )


class TestNoMutableClassDefault:
    """Regression: _FakeRecord must not use mutable class-level default."""

    def test_shutdown_analysis_fake_record(self) -> None:
        import tests.test_shutdown_analysis as mod

        src = inspect.getsource(mod)
        # Should not have `latest_metrics: dict = {}` as class-level
        assert "latest_metrics: dict = {}" not in src, (
            "Must use __init__ or field(default_factory=dict)"
        )
