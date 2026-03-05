"""Cross-cutting review guardrail regressions (core set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

from vibesensor.domain_models import (
    as_float_or_none,
    as_int_or_none,
    new_car_id,
    sanitize_aspects,
)

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


class TestDomainModelsPublicAPI:
    """Verify that formerly-private helpers are importable by their public names."""

    def test_as_float_or_none_importable(self) -> None:
        assert as_float_or_none(3.14) == 3.14
        assert as_float_or_none(None) is None
        assert as_float_or_none("") is None
        assert as_float_or_none(float("nan")) is None
        assert as_float_or_none(float("inf")) is None

    def test_as_int_or_none_importable(self) -> None:
        assert as_int_or_none(3.7) == 4
        assert as_int_or_none(None) is None

    def test_sanitize_aspects_importable(self) -> None:
        result = sanitize_aspects({"tire_width_mm": 225.0})
        assert "tire_width_mm" in result

    def test_new_car_id_importable(self) -> None:
        car_id = new_car_id()
        assert isinstance(car_id, str) and len(car_id) > 0

    def test_domain_models_has_all(self) -> None:
        import vibesensor.domain_models as dm

        assert hasattr(dm, "__all__")
        assert "as_float_or_none" in dm.__all__
        assert "CarConfig" in dm.__all__

    def test_runlog_re_exports(self) -> None:
        """runlog.as_float_or_none still works as before."""
        from vibesensor.runlog import as_float_or_none as runlog_as_float

        assert runlog_as_float(42) == 42.0
