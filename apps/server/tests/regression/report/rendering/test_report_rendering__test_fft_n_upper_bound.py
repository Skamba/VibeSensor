"""Report rendering regressions:
- Next-step numbering continues across pages (start_number param)
- SystemFindingCard.tone wired to theme colors
- NextStep confirm/falsify/eta rendered
- fft_n upper bound clamped at 65536
- Orphan g-unit i18n keys removed
- Test quality: no global random.seed, no mutable class-level dict
"""

from __future__ import annotations

import pytest


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
        "fft_n, expected",
        [
            pytest.param(2**20, 65536, id="absurd_clamped"),
            pytest.param(4096, 4096, id="normal_unchanged"),
            pytest.param(65536, 65536, id="max_boundary"),
        ],
    )
    def test_fft_n_clamping(self, fft_n: int, expected: int) -> None:
        cfg = _make_processing_config(fft_n=fft_n)
        assert cfg.fft_n == expected
