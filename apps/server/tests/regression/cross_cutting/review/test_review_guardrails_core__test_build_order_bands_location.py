"""Cross-cutting review guardrail regressions (core set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

from vibesensor.diagnostics_shared import build_order_bands

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


class TestBuildOrderBandsLocation:
    def test_importable_from_diagnostics_shared(self) -> None:
        assert callable(build_order_bands)

    def test_not_in_runtime(self) -> None:
        """The old _build_order_bands should not exist in runtime anymore."""
        import vibesensor.runtime as rt

        assert not hasattr(rt, "_build_order_bands")

    def test_build_order_bands_basic(self) -> None:
        orders = {
            "wheel_hz": 10.0,
            "drive_hz": 30.0,
            "engine_hz": 60.0,
            "wheel_uncertainty_pct": 0.02,
            "drive_uncertainty_pct": 0.03,
            "engine_uncertainty_pct": 0.04,
        }
        settings = {}
        bands = build_order_bands(orders, settings)
        assert isinstance(bands, list)
        assert len(bands) >= 4  # wheel_1x, wheel_2x, drive/engine, engine_2x
        keys = [b["key"] for b in bands]
        assert "wheel_1x" in keys
        assert "wheel_2x" in keys
        assert "engine_2x" in keys
