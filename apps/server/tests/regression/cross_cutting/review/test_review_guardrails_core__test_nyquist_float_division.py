"""Cross-cutting review guardrail regressions (core set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

from vibesensor.config import ProcessingConfig

_PROCESSING_DEFAULTS = dict(
    waveform_seconds=8,
    waveform_display_hz=120,
    ui_push_hz=10,
    ui_heavy_push_hz=4,
    fft_update_hz=4,
    fft_n=2048,
    spectrum_min_hz=5.0,
    client_ttl_seconds=120,
    accel_scale_g_per_lsb=None,
)


class TestNyquistFloatDivision:
    def test_odd_sample_rate_nyquist(self) -> None:
        cfg = ProcessingConfig(sample_rate_hz=801, spectrum_max_hz=400, **_PROCESSING_DEFAULTS)
        assert cfg.spectrum_max_hz == 400  # NOT clamped to 399

    def test_even_sample_rate_still_clamps(self) -> None:
        cfg = ProcessingConfig(sample_rate_hz=800, spectrum_max_hz=400, **_PROCESSING_DEFAULTS)
        assert cfg.spectrum_max_hz == 399  # clamped
