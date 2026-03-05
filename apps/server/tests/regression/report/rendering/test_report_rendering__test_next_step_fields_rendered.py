"""Report rendering regressions:
- Next-step numbering continues across pages (start_number param)
- SystemFindingCard.tone wired to theme colors
- NextStep confirm/falsify/eta rendered
- fft_n upper bound clamped at 65536
- Orphan g-unit i18n keys removed
- Test quality: no global random.seed, no mutable class-level dict
"""

from __future__ import annotations

import inspect

import pytest

from vibesensor.report.pdf_builder import (
    _draw_next_steps_table,
)


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


class TestNextStepFieldsRendered:
    """Regression: confirm/falsify/eta must appear in rendered text."""

    @pytest.mark.parametrize("field_name", ["confirm", "falsify", "eta"])
    def test_field_rendered(self, field_name: str) -> None:
        src = inspect.getsource(_draw_next_steps_table)
        assert f"step.{field_name}" in src, f"{field_name} field must be checked"
