from __future__ import annotations

import numpy as np
import pytest

from vibesensor.dsp.strength_bands import (
    _buckets_for_strength_db_aligned,
    bucket_for_strength,
)

# -- bucket_for_strength -------------------------------------------------------


@pytest.mark.parametrize(
    ("vibration_strength_db", "expected"),
    [
        pytest.param(-5.0, "l0", id="negative"),
        pytest.param(0.0, "l0", id="zero"),
        pytest.param(5.0, "l0", id="below-first-threshold"),
        pytest.param(7.9, "l0", id="just-below-l1"),
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
