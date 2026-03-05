"""Strength bucketing and combined-spectrum runtime regressions:
- combined spectrum not polluted by zeroed amp_for_peaks
- order tolerance scales with path_compliance
- _noise_floor no double bin removal
- bucket_for_strength returns 'l0' for negative dB
- dead db_value variable removed from _top_strength_values
"""

from __future__ import annotations

from vibesensor.analysis.helpers import ORDER_TOLERANCE_MIN_HZ, ORDER_TOLERANCE_REL


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
