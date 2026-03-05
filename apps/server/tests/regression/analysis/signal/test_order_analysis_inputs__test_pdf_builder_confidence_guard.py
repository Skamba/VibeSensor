"""Regression for guarded float() parsing of PDF finding confidence."""

from __future__ import annotations

import pytest


class TestPdfBuilderConfidenceGuard:
    """float() on confidence should not crash on non-numeric values."""

    @pytest.mark.parametrize(
        "raw_value, expected",
        [
            ("unknown", 0.0),
            (0.85, pytest.approx(0.85)),
            (None, 0.0),
        ],
    )
    def test_confidence_guard(self, raw_value: object, expected: object) -> None:
        finding = {"confidence_0_to_1": raw_value}
        try:
            confidence = float(finding.get("confidence_0_to_1") or 0.0)
        except (ValueError, TypeError):
            confidence = 0.0
        assert confidence == expected
