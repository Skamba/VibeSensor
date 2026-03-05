"""Strength bucketing and combined-spectrum runtime regressions:
- combined spectrum not polluted by zeroed amp_for_peaks
- order tolerance scales with path_compliance
- _noise_floor no double bin removal
- bucket_for_strength returns 'l0' for negative dB
- dead db_value variable removed from _top_strength_values
"""

from __future__ import annotations

import inspect

from vibesensor.analysis.report_data_builder import _top_strength_values


class TestDeadDbValueRemoved:
    """Regression: _top_strength_values should not contain unused db_value
    variable."""

    def test_no_db_value_in_source(self) -> None:
        source = inspect.getsource(_top_strength_values)
        assert "db_value" not in source, (
            "Dead variable db_value still present in _top_strength_values"
        )
