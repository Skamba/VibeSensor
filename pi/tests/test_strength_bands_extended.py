from __future__ import annotations

from vibesensor.strength_bands import band_by_key, band_rank, bucket_for_strength

# -- bucket_for_strength -------------------------------------------------------


def test_bucket_below_threshold_returns_none() -> None:
    assert bucket_for_strength(strength_db=5.0, band_rms=0.001) is None


def test_bucket_l1_threshold() -> None:
    assert bucket_for_strength(strength_db=10.0, band_rms=0.003) == "l1"


def test_bucket_l5_threshold() -> None:
    assert bucket_for_strength(strength_db=34.0, band_rms=0.048) == "l5"


def test_bucket_returns_highest_matching() -> None:
    # Meets L1-L3 thresholds → returns L3
    result = bucket_for_strength(strength_db=22.0, band_rms=0.012)
    assert result == "l3"


def test_bucket_zero_band_rms_returns_none() -> None:
    assert bucket_for_strength(strength_db=50.0, band_rms=0.0) is None


def test_bucket_negative_band_rms_returns_none() -> None:
    assert bucket_for_strength(strength_db=50.0, band_rms=-0.01) is None


def test_bucket_db_meets_but_amp_too_low() -> None:
    # dB high enough for l3 but amplitude below l2 threshold
    assert bucket_for_strength(strength_db=22.0, band_rms=0.005) == "l1"


# -- band_by_key ---------------------------------------------------------------


def test_band_by_key_valid() -> None:
    band = band_by_key("l1")
    assert band is not None
    assert band["min_db"] == 10.0


def test_band_by_key_l5() -> None:
    band = band_by_key("l5")
    assert band is not None
    assert band["min_db"] == 34.0


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
