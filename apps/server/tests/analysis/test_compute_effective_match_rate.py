"""Unit tests for _compute_effective_match_rate speed-band rescue logic.

Covers the highest-speed-bin rescue path and per-location fallback.
"""

from __future__ import annotations

import pytest

from vibesensor.analysis.orders.match_rate import _compute_effective_match_rate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bins(*specs: tuple[str, int, int]) -> tuple[dict[str, int], dict[str, int]]:
    """Build possible/matched dicts from (label, possible, matched) tuples."""
    possible = {label: p for label, p, _m in specs}
    matched = {label: m for label, _p, m in specs}
    return possible, matched


def _run_rescue(
    match_rate: float,
    speed_specs: tuple[tuple[str, int, int], ...],
    *,
    min_match_rate: float = 0.25,
    possible_by_location: dict[str, int] | None = None,
    matched_by_location: dict[str, int] | None = None,
) -> tuple[float, str | None, bool]:
    """Call ``_compute_effective_match_rate`` with common defaults."""
    possible, matched = _bins(*speed_specs)
    return _compute_effective_match_rate(
        match_rate=match_rate,
        min_match_rate=min_match_rate,
        possible_by_speed_bin=possible,
        matched_by_speed_bin=matched,
        possible_by_location=possible_by_location or {},
        matched_by_location=matched_by_location or {},
    )


# Only the highest speed bin is a rescue candidate; it needs enough samples and a
# match rate above ``min_match_rate``. Per-location dominance is the last fallback.
@pytest.mark.parametrize(
    ("match_rate", "speed_specs", "location_counts", "expected"),
    [
        pytest.param(
            0.20,
            (("30-40 km/h", 10, 2), ("90-100 km/h", 10, 8)),
            None,
            (0.8, "90-100 km/h", False),
            id="highest-bin-qualifies",
        ),
        pytest.param(
            0.20,
            (("30-40 km/h", 10, 9), ("50-60 km/h", 6, 1), ("90-100 km/h", 8, 1)),
            None,
            (0.20, None, False),
            id="strong-low-speed-bin-not-rescued",
        ),
        pytest.param(
            0.20,
            (("40-50 km/h", 10, 3), ("70-80 km/h", 10, 8), ("90-100 km/h", 6, 1)),
            None,
            (0.20, None, False),
            id="strong-second-highest-bin-ignored",
        ),
        pytest.param(
            0.20,
            (("60-70 km/h", 10, 7), ("80-90 km/h", 10, 9), ("90-100 km/h", 10, 8)),
            None,
            (0.8, "90-100 km/h", False),
            id="highest-bin-wins-over-better-lower-bin",
        ),
        pytest.param(
            0.20,
            (
                ("30-40 km/h", 10, 10),
                ("60-70 km/h", 6, 1),
                ("70-80 km/h", 6, 1),
                ("90-100 km/h", 6, 1),
            ),
            None,
            (0.20, None, False),
            id="only-highest-bin-evaluated",
        ),
        pytest.param(
            0.50,
            (("80-90 km/h", 10, 8),),
            None,
            (0.50, None, False),
            id="no-rescue-when-global-rate-sufficient",
        ),
        pytest.param(0.10, (), None, (0.10, None, False), id="empty-speed-bins"),
        pytest.param(
            0.10,
            (("90-100 km/h", 2, 2),),
            None,
            (0.10, None, False),
            id="bin-with-too-few-samples-skipped",
        ),
        pytest.param(
            0.10,
            (("90-100 km/h", 6, 1),),
            ({"Front Left": 10}, {"Front Left": 8}),
            (0.8, None, True),
            id="per-location-fallback-after-speed-rescue-fails",
        ),
    ],
)
def test_compute_effective_match_rate(
    match_rate: float,
    speed_specs: tuple[tuple[str, int, int], ...],
    location_counts: tuple[dict[str, int], dict[str, int]] | None,
    expected: tuple[float, str | None, bool],
) -> None:
    possible_by_location, matched_by_location = location_counts or ({}, {})
    assert (
        _run_rescue(
            match_rate,
            speed_specs,
            possible_by_location=possible_by_location,
            matched_by_location=matched_by_location,
        )
        == expected
    )
