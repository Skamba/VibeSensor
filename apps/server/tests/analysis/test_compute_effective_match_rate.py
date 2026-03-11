"""Unit tests for _compute_effective_match_rate speed-band rescue logic.

Covers the highest-speed-bin rescue path and per-location fallback.
"""

from __future__ import annotations

from vibesensor.analysis.order_analysis import _compute_effective_match_rate

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


# ---------------------------------------------------------------------------
# 1. Happy path – highest bin qualifies (existing behaviour preserved)
# ---------------------------------------------------------------------------


def test_highest_bin_qualifies() -> None:
    eff, band, loc_dom = _run_rescue(
        0.20,
        (("30-40 km/h", 10, 2), ("90-100 km/h", 10, 8)),
    )
    assert band == "90-100 km/h"
    assert eff == 0.8
    assert loc_dom is False


# ---------------------------------------------------------------------------
# 2. Fault prominent at low speed – highest bin poor
# ---------------------------------------------------------------------------


def test_low_speed_fault_not_rescued_when_highest_bin_poor() -> None:
    """Only the highest speed bin is evaluated; a lower bin with strong
    signal will not be rescued via speed-band path.
    """
    eff, band, loc_dom = _run_rescue(
        0.20,
        (
            ("30-40 km/h", 10, 9),  # 90% match rate – strong signal but not highest
            ("50-60 km/h", 6, 1),  # noise
            ("90-100 km/h", 8, 1),  # noise at highest bin
        ),
    )
    # Highest bin (90-100) doesn’t qualify → no speed-band rescue
    # Highest bin (90-100) doesn't qualify → no speed-band rescue
    assert band is None
    assert eff == 0.20
    assert loc_dom is False


# ---------------------------------------------------------------------------
# 3. Second-highest bin qualifies
# ---------------------------------------------------------------------------


def test_second_highest_bin_not_considered() -> None:
    """Only the highest speed bin is checked; a strong second bin is ignored."""
    eff, band, _ = _run_rescue(
        0.20,
        (
            ("40-50 km/h", 10, 3),
            ("70-80 km/h", 10, 8),  # strong but not highest
            ("90-100 km/h", 6, 1),  # poor – highest
        ),
    )
    # Highest bin (90-100) doesn’t qualify → no rescue
    # Highest bin (90-100) doesn't qualify → no rescue
    assert band is None
    assert eff == 0.20


# ---------------------------------------------------------------------------
# 4. Multiple bins qualify – pick the one with best rate
# ---------------------------------------------------------------------------


def test_highest_bin_wins_even_when_lower_bin_has_better_rate() -> None:
    """The highest speed bin is always the rescue candidate, even if a lower
    bin has a better match rate.
    """
    eff, band, _ = _run_rescue(
        0.20,
        (
            ("60-70 km/h", 10, 7),  # 70%
            ("80-90 km/h", 10, 9),  # 90% – best rate
            ("90-100 km/h", 10, 8),  # 80% – highest bin
        ),
    )
    # Highest bin (90-100) qualifies → used for rescue (not 80-90)
    assert band == "90-100 km/h"
    assert eff == 0.8


# ---------------------------------------------------------------------------
# 5. Fourth bin is not evaluated (only top-3)
# ---------------------------------------------------------------------------


def test_only_highest_bin_evaluated() -> None:
    """Only the highest speed bin is checked for rescue."""
    eff, band, _ = _run_rescue(
        0.20,
        (
            ("30-40 km/h", 10, 10),  # perfect — but not highest
            ("60-70 km/h", 6, 1),  # noise
            ("70-80 km/h", 6, 1),  # noise
            ("90-100 km/h", 6, 1),  # noise – highest
        ),
    )
    # Highest bin (90-100) doesn’t qualify → no rescue
    # Highest bin (90-100) doesn't qualify → no rescue
    assert band is None
    assert eff == 0.20


# ---------------------------------------------------------------------------
# 6. No rescue needed – global rate above threshold
# ---------------------------------------------------------------------------


def test_no_rescue_when_global_rate_sufficient() -> None:
    eff, band, _ = _run_rescue(
        0.50,
        (("80-90 km/h", 10, 8),),
    )
    assert band is None  # no rescue attempted
    assert eff == 0.50


# ---------------------------------------------------------------------------
# 7. Empty speed bins – no crash
# ---------------------------------------------------------------------------


def test_empty_speed_bins_no_crash() -> None:
    eff, band, loc_dom = _run_rescue(0.10, ())
    assert band is None
    assert eff == 0.10
    assert loc_dom is False


# ---------------------------------------------------------------------------
# 8. Insufficient focused_possible – bin skipped
# ---------------------------------------------------------------------------


def test_bin_with_too_few_samples_skipped() -> None:
    eff, band, _ = _run_rescue(
        0.10,
        (("90-100 km/h", 2, 2),),  # 100% rate but only 2 samples – below minimum
    )
    assert band is None
    assert eff == 0.10


# ---------------------------------------------------------------------------
# 9. Per-location fallback still works after speed-band rescue fails
# ---------------------------------------------------------------------------


def test_per_location_fallback_after_speed_rescue_fails() -> None:
    eff, band, loc_dom = _run_rescue(
        0.10,
        (("90-100 km/h", 6, 1),),  # poor
        possible_by_location={"Front Left": 10},
        matched_by_location={"Front Left": 8},
    )
    assert band is None  # speed rescue failed
    assert loc_dom is True  # per-location kicked in
    assert eff == 0.8
