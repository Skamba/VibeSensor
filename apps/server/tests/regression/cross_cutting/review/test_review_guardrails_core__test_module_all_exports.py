"""Cross-cutting review guardrail regressions (core set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

import importlib

import pytest

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


class TestModuleAllExports:
    @pytest.mark.parametrize(
        "module_path",
        [
            "vibesensor.domain_models",
            "vibesensor.protocol",
            "vibesensor.worker_pool",
            "vibesensor.car_library",
            "vibesensor.gps_speed",
            "vibesensor.registry",
        ],
    )
    def test_module_has_all(self, module_path: str) -> None:
        mod = importlib.import_module(module_path)
        assert hasattr(mod, "__all__"), f"{module_path} is missing __all__"
        assert len(mod.__all__) > 0, f"{module_path}.__all__ is empty"
