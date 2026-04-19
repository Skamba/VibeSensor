"""Behavior tests for HTTP safe filename sanitization."""

from __future__ import annotations

import pytest

from vibesensor.adapters.http._helpers import safe_filename as _safe_filename


class TestSafeFilename:
    """Cover exact sanitization outputs, special-character replacement, and truncation."""

    @pytest.mark.parametrize(
        ("input_name", "expected"),
        [
            ("run-2026-01-01_abc", "run-2026-01-01_abc"),
            ("", "download"),
            ("///", "___"),
        ],
    )
    def test_exact_output(self, input_name: str, expected: str) -> None:
        assert _safe_filename(input_name) == expected

    def test_special_chars_replaced(self) -> None:
        result = _safe_filename("run/with spaces & $pecial")
        assert "/" not in result
        assert " " not in result
        assert "$" not in result

    def test_long_name_truncated(self) -> None:
        result = _safe_filename("a" * 500)
        assert len(result) <= 200
