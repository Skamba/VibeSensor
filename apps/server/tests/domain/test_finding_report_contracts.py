"""Focused Finding contract tests."""

from __future__ import annotations

import pytest

from vibesensor.domain.finding import Finding


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_finding_rejects_out_of_range_confidence(confidence: float) -> None:
    with pytest.raises(ValueError, match="must be in \\[0, 1\\]"):
        Finding(confidence=confidence)
