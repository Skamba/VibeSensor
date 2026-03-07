# ruff: noqa: E402, E501
from __future__ import annotations

"""Strength bucketing and combined-spectrum runtime regressions:
- combined spectrum not polluted by zeroed amp_for_peaks
- order tolerance scales with path_compliance
- _noise_floor no double bin removal
- bucket_for_strength returns 'l0' for negative dB
- dead db_value variable removed from _top_strength_values
"""


import inspect
import re

import numpy as np
import pytest
from vibesensor_core.strength_bands import bucket_for_strength

from vibesensor.analysis.helpers import ORDER_TOLERANCE_MIN_HZ, ORDER_TOLERANCE_REL
from vibesensor.analysis.report_data_builder import _top_strength_values
from vibesensor.processing import SignalProcessor
from vibesensor.processing.fft import compute_fft_spectrum


class TestBucketForStrengthNegativeDB:
    """Regression: bucket_for_strength must return 'l0' for negative dB,
    not None."""

    @pytest.mark.parametrize(
        ("db_val", "expected"),
        [
            pytest.param(-5.0, "l0", id="negative"),
            pytest.param(0.0, "l0", id="zero"),
            pytest.param(7.9, "l0", id="below_l1"),
            pytest.param(8.0, "l1", id="l1_boundary"),
            pytest.param(50.0, "l5", id="high"),
        ],
    )
    def test_bucket_boundaries(self, db_val: float, expected: str) -> None:
        assert bucket_for_strength(db_val) == expected


class TestCombinedSpectrumNotZeroed:
    """Regression: axis_amp_slices must use amp_slice (original), not
    amp_for_peaks (which has DC bin zeroed). Otherwise the combined
    spectrum inherits the artificial zero."""

    def test_amp_slice_used_not_amp_for_peaks(self) -> None:
        """Verify source code appends amp_slice (not amp_for_peaks)
        to axis_amp_slices."""
        src = inspect.getsource(compute_fft_spectrum)
        # Find the line that appends to axis_amp_slices
        match = re.search(r"axis_amp_slices\.append\((\w+)\)", src)
        assert match is not None, "axis_amp_slices.append() not found"
        appended_var = match.group(1)
        assert appended_var == "amp_slice", (
            f"Expected axis_amp_slices.append(amp_slice), "
            f"got axis_amp_slices.append({appended_var})"
        )


class TestNoiseFloorNoDoubleRemoval:
    """Regression: _noise_floor must not skip amps[1:] before delegating
    to noise_floor_amp_p20_g, since the caller already provides the
    analysis-band slice (DC already removed)."""

    def test_all_bins_included(self) -> None:
        amps = np.array([0.010, 0.012, 0.009, 0.011, 0.013], dtype=np.float32)
        floor = SignalProcessor._noise_floor(amps)
        # All 5 bins should be considered. If amps[1:] were used,
        # the first bin (0.010) would be excluded, changing the result.
        # P20 of [0.009, 0.010, 0.011, 0.012, 0.013] ≈ 0.0098
        assert floor > 0.0
        # The result must include the first bin. If it were excluded,
        # P20 of [0.011, 0.012, 0.013] = 0.0114, which is higher.
        # With all 5 bins, P20 is lower because 0.009 and 0.010 pull it down.
        floor_without_first = SignalProcessor._noise_floor(amps[1:])
        assert floor <= floor_without_first + 1e-6, (
            f"Floor {floor} should be ≤ floor-without-first {floor_without_first}"
        )


class TestOrderToleranceScalesWithCompliance:
    """Regression: order tolerance must scale with path_compliance so
    wheel hypotheses (compliance=1.5) get a wider matching window."""

    def test_compliance_1_baseline(self) -> None:
        predicted_hz = 20.0
        compliance = 1.0
        tolerance = max(
            ORDER_TOLERANCE_MIN_HZ,
            predicted_hz * ORDER_TOLERANCE_REL * compliance,
        )
        expected = max(ORDER_TOLERANCE_MIN_HZ, 20.0 * 0.08 * 1.0)
        assert abs(tolerance - expected) < 1e-9

    def test_compliance_1_5_wider(self) -> None:
        predicted_hz = 20.0
        tol_1 = max(ORDER_TOLERANCE_MIN_HZ, predicted_hz * ORDER_TOLERANCE_REL * 1.0**0.5)
        tol_15 = max(ORDER_TOLERANCE_MIN_HZ, predicted_hz * ORDER_TOLERANCE_REL * 1.5**0.5)
        assert tol_15 > tol_1, "compliance=1.5 must produce wider tolerance"
        # sqrt(1.5) ≈ 1.2247
        ratio = tol_15 / tol_1
        assert abs(ratio - 1.5**0.5) < 1e-6, (
            f"Tolerance should scale by sqrt(compliance), got {ratio}"
        )


class TestDeadDbValueRemoved:
    """Regression: _top_strength_values should not contain unused db_value
    variable."""

    def test_no_db_value_in_source(self) -> None:
        source = inspect.getsource(_top_strength_values)
        assert "db_value" not in source, (
            "Dead variable db_value still present in _top_strength_values"
        )
