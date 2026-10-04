"""Amplitude-weighted speed helpers ignore empty, weightless and standing-still inputs."""

from __future__ import annotations

from vibesensor.analysis.math_utils import _weighted_percentile
from vibesensor.analysis.speed_profile_helpers import _speed_profile_from_points


def test_weighted_percentile_of_nothing_is_none() -> None:
    assert _weighted_percentile([], 0.5) is None
    assert _weighted_percentile([(10.0, 0.0), (20.0, 0.0)], 0.5) is None


def test_speed_profile_ignores_standing_still() -> None:
    peak_speed, _band, _label = _speed_profile_from_points([(0.0, 0.06), (80.0, 0.08)])
    assert peak_speed == 80.0
