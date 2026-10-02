"""Focused Finding contract tests."""

from __future__ import annotations

import pytest

from vibesensor.domain.finding import Finding


@pytest.mark.parametrize(
    ("confidence", "expected_pct"),
    [
        (None, None),
        (0.0, 0),
        (0.0049, 0),
        (0.005, 0),
        (0.0051, 1),
        (0.245, 24),
        (0.255, 26),
        (0.9949, 99),
        (0.995, 100),
        (1.0, 100),
    ],
)
def test_finding_confidence_pct_covers_rounding_boundaries(
    confidence: float | None,
    expected_pct: int | None,
) -> None:
    finding = Finding(confidence=confidence)

    assert finding.confidence_pct == expected_pct


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_finding_rejects_out_of_range_confidence(confidence: float) -> None:
    with pytest.raises(ValueError, match="must be in \\[0, 1\\]"):
        Finding(confidence=confidence)
