from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest
from _paths import REPO_ROOT

from vibesensor.strength_bands import (
    BANDS,
    _buckets_for_strength_db_aligned,
    bucket_for_strength,
)

# -- bucket_for_strength -------------------------------------------------------


@pytest.mark.parametrize(
    ("vibration_strength_db", "expected"),
    [
        pytest.param(0.0, "l0", id="zero"),
        pytest.param(5.0, "l0", id="below-first-threshold"),
        pytest.param(8.0, "l1", id="l1-threshold"),
        pytest.param(26.0, "l3", id="highest-matching-threshold"),
        pytest.param(46.0, "l5", id="l5-threshold"),
    ],
)
def test_bucket_examples(vibration_strength_db: float, expected: str) -> None:
    assert bucket_for_strength(vibration_strength_db=vibration_strength_db) == expected


def test_batch_buckets_match_scalar_helper() -> None:
    values = np.array([-5.0, 0.0, 7.9, 8.0, 15.9, 16.0, 45.9, 46.0, 120.0], dtype=np.float64)
    result = _buckets_for_strength_db_aligned(values)
    expected = [bucket_for_strength(float(value)) for value in values]
    assert result == expected


# -- UI i18n severity labels match core BANDS -----------------------------------

_UI_CATALOGS_DIR = REPO_ROOT / "apps" / "ui" / "src" / "i18n" / "catalogs"

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


@pytest.mark.parametrize("locale", ["en", "nl"])
def test_ui_severity_labels_match_core_bands(locale: str) -> None:
    catalog = _UI_CATALOGS_DIR / f"{locale}.json"
    assert catalog.exists(), f"{locale}.json not found at {catalog}"
    _check_catalog(catalog)
