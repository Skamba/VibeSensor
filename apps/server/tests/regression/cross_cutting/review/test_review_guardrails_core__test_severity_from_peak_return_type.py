"""Cross-cutting review guardrail regressions (core set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

import pytest

from vibesensor.diagnostics_shared import severity_from_peak

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


class TestSeverityFromPeakReturnType:
    @pytest.mark.parametrize(
        "db, sensor_count, prior_state",
        [
            (-100.0, 0, None),
            (50.0, 1, None),
            (5.0, 1, {"current_bucket": "l2", "pending_bucket": None}),
        ],
    )
    def test_returns_dict(self, db: float, sensor_count: int, prior_state) -> None:
        result = severity_from_peak(
            vibration_strength_db=db, sensor_count=sensor_count, prior_state=prior_state
        )
        assert isinstance(result, dict)
        assert "key" in result
        assert "db" in result
        assert "state" in result
