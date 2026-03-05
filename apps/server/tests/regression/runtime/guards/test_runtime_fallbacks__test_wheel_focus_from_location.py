"""Runtime fallback and error-guard regressions.

Covers strength_floor_amp_g fallback, wheel_focus_from_location,
store_analysis_error guard, and i18n formatting.
"""

from __future__ import annotations

import pytest

from vibesensor.analysis.order_analysis import _wheel_focus_from_location


class TestWheelFocusFromLocation:
    """Regression: _wheel_focus_from_location must match label_for_code() outputs
    which use spaces (e.g. 'Front Left Wheel'), not hyphens."""

    @pytest.mark.parametrize(
        "label, expected_key",
        [
            # Space-separated (canonical)
            ("Front Left Wheel", "WHEEL_FOCUS_FRONT_LEFT"),
            ("Front Right Wheel", "WHEEL_FOCUS_FRONT_RIGHT"),
            ("Rear Left Wheel", "WHEEL_FOCUS_REAR_LEFT"),
            ("Rear Right Wheel", "WHEEL_FOCUS_REAR_RIGHT"),
            # Hyphen-separated
            ("front-left wheel", "WHEEL_FOCUS_FRONT_LEFT"),
            ("rear-right wheel", "WHEEL_FOCUS_REAR_RIGHT"),
            # Underscore-separated
            ("front_left_wheel", "WHEEL_FOCUS_FRONT_LEFT"),
            ("rear_left_wheel", "WHEEL_FOCUS_REAR_LEFT"),
            # Generic locations
            ("Trunk", "WHEEL_FOCUS_REAR"),
            ("Engine Bay", "WHEEL_FOCUS_FRONT"),
            ("unknown location", "WHEEL_FOCUS_ALL"),
        ],
    )
    def test_location_to_wheel_focus(self, label: str, expected_key: str) -> None:
        assert _wheel_focus_from_location(label) == {"_i18n_key": expected_key}
