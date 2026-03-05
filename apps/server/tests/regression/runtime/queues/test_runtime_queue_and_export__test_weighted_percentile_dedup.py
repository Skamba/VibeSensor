"""Runtime queue/history tracking and export-filter regressions."""

from __future__ import annotations

from vibesensor.analysis.findings import _weighted_percentile
from vibesensor.analysis.test_plan import _weighted_percentile_speed

_DEAD_FUNCTION_CASES = [
    ("vibesensor/report/pdf_builder.py", "_measure_text_height"),
    ("vibesensor/report/pdf_diagram.py", "_amp_heat_color"),
    ("vibesensor/report/pdf_diagram.py", "def _format_db"),
    ("vibesensor/firmware_cache.py", "def install_baseline"),
]


class TestWeightedPercentileDedup:
    def test_weighted_percentile_speed_delegates(self) -> None:
        """_weighted_percentile_speed should match _weighted_percentile for positive speeds."""
        pairs = [(60.0, 2.0), (80.0, 3.0), (100.0, 1.0)]
        for q in [0.0, 0.1, 0.5, 0.9, 1.0]:
            result = _weighted_percentile_speed(pairs, q)
            expected = _weighted_percentile(pairs, q)
            assert result == expected, f"Mismatch at q={q}: {result} != {expected}"

    def test_weighted_percentile_speed_filters_negative(self) -> None:
        pairs = [(-10.0, 5.0), (50.0, 1.0)]
        result = _weighted_percentile_speed(pairs, 0.5)
        assert result == 50.0
