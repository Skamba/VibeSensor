from __future__ import annotations

import json
import re
from pathlib import Path

from vibesensor_core.strength_bands import BANDS, band_by_key, band_rank, bucket_for_strength

# -- bucket_for_strength -------------------------------------------------------


def test_bucket_below_threshold_returns_l0() -> None:
    assert bucket_for_strength(vibration_strength_db=0.0) == "l0"
    assert bucket_for_strength(vibration_strength_db=5.0) == "l0"


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


def test_band_by_key_l0() -> None:
    band = band_by_key("l0")
    assert band is not None
    assert band["min_db"] == 0.0


def test_band_by_key_l5() -> None:
    band = band_by_key("l5")
    assert band is not None
    assert band["min_db"] == 46.0


def test_band_by_key_unknown() -> None:
    assert band_by_key("l99") is None
    assert band_by_key("") is None


# -- band_rank -----------------------------------------------------------------


def test_band_rank_ordering() -> None:
    assert band_rank("l0") == 0
    assert band_rank("l1") == 1
    assert band_rank("l5") == 5
    assert band_rank("l3") == 3


def test_band_rank_unknown_returns_neg1() -> None:
    assert band_rank("unknown") == -1


# -- UI i18n severity labels match core BANDS -----------------------------------

_UI_CATALOGS_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "apps"
    / "ui"
    / "src"
    / "i18n"
    / "catalogs"
)

# Build expected thresholds: each band's range is [min_db, next_band.min_db)
_EXPECTED: dict[str, tuple[float, float | None]] = {}
for _i, _band in enumerate(BANDS):
    _next_min = BANDS[_i + 1]["min_db"] if _i + 1 < len(BANDS) else None
    _EXPECTED[_band["key"]] = (_band["min_db"], _next_min)

# Regex to extract dB range from labels like "L3 Elevated (26-36 dB)" or "L5 Critical (>=46 dB)"
_RANGE_RE = re.compile(r"\(>=?(\d+(?:\.\d+)?)\s*dB\)")
_PAIR_RE = re.compile(r"\((\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*dB\)")


def _check_catalog(catalog_path: Path) -> None:
    """Assert that matrix.severity.* labels in *catalog_path* match core BANDS."""
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    for key, (lo, hi) in _EXPECTED.items():
        label_key = f"matrix.severity.{key}"
        if key == "l0":
            # l0 is typically not shown in UI severity legend
            continue
        assert label_key in data, f"{label_key} missing from {catalog_path.name}"
        label = data[label_key]
        if hi is None:
            # Highest band: expect >=<lo> dB
            m = _RANGE_RE.search(label)
            assert m is not None, f"Cannot parse dB from {label!r} in {catalog_path.name}"
            assert float(m.group(1)) == lo, (
                f"{catalog_path.name} {label_key}: expected >={lo} dB, got >={m.group(1)} dB"
            )
        else:
            # Range band: expect <lo>-<hi> dB
            m = _PAIR_RE.search(label)
            assert m is not None, f"Cannot parse dB range from {label!r} in {catalog_path.name}"
            assert float(m.group(1)) == lo, (
                f"{catalog_path.name} {label_key}: expected low {lo}, got {m.group(1)}"
            )
            assert float(m.group(2)) == hi, (
                f"{catalog_path.name} {label_key}: expected high {hi}, got {m.group(2)}"
            )


def test_ui_en_severity_labels_match_core_bands() -> None:
    en_path = _UI_CATALOGS_DIR / "en.json"
    assert en_path.exists(), f"en.json not found at {en_path}"
    _check_catalog(en_path)


def test_ui_nl_severity_labels_match_core_bands() -> None:
    nl_path = _UI_CATALOGS_DIR / "nl.json"
    assert nl_path.exists(), f"nl.json not found at {nl_path}"
    _check_catalog(nl_path)
