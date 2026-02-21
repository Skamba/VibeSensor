from __future__ import annotations

from vibesensor_core.strength_bands import band_by_key, band_rank, bucket_for_strength

# -- bucket_for_strength -------------------------------------------------------


def test_bucket_below_threshold_returns_none() -> None:
    assert bucket_for_strength(vibration_strength_db=5.0) is None


def test_bucket_l1_threshold() -> None:
    assert bucket_for_strength(vibration_strength_db=8.0) == "l1"


def test_bucket_l5_threshold() -> None:
    assert bucket_for_strength(vibration_strength_db=46.0) == "l5"


def test_bucket_returns_highest_matching() -> None:
    # Meets L1-L3 thresholds → returns L3
    result = bucket_for_strength(vibration_strength_db=26.0)
    assert result == "l3"


# -- band_by_key ---------------------------------------------------------------


def test_band_by_key_valid() -> None:
    band = band_by_key("l1")
    assert band is not None
    assert band["min_db"] == 8.0


def test_band_by_key_l5() -> None:
    band = band_by_key("l5")
    assert band is not None
    assert band["min_db"] == 46.0


def test_band_by_key_unknown() -> None:
    assert band_by_key("l99") is None
    assert band_by_key("") is None


# -- band_rank -----------------------------------------------------------------


def test_band_rank_ordering() -> None:
    assert band_rank("l1") == 0
    assert band_rank("l5") == 4
    assert band_rank("l3") == 2


def test_band_rank_unknown_returns_neg1() -> None:
    assert band_rank("unknown") == -1
