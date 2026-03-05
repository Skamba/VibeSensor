"""Cross-cutting review guardrail regressions (core set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

import inspect

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


class TestCarLibraryImport:
    def test_copy_at_module_level(self) -> None:
        """copy should be importable from car_library's module scope."""
        import vibesensor.car_library as cl

        source = inspect.getsource(cl)
        # Must have top-level `import copy`, not inside a function
        lines = source.split("\n")
        # Find lines that are `import copy` at indentation level 0
        top_level_copy_import = any(
            line.strip() == "import copy" and not line.startswith(" ") for line in lines
        )
        assert top_level_copy_import, "import copy must be at module level"
