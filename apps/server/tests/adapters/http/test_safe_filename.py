"""Behavior tests for HTTP safe filename sanitization."""

from __future__ import annotations

import pytest

from vibesensor.adapters.http._helpers import safe_filename as _safe_filename


class TestSafeFilename:
    """Cover exact sanitization outputs, special-character replacement, and truncation."""

    @pytest.mark.parametrize(
        ("input_name", "expected"),
        [
            pytest.param("run-2026-01-01_abc", "run-2026-01-01_abc", id="safe-name-kept"),
            pytest.param("", "download", id="empty-name-uses-download"),
            pytest.param("///", "___", id="path-separators-replaced"),
            pytest.param(".hidden", "hidden", id="leading-dot-stripped"),
            pytest.param("...", "download", id="dot-only-name-uses-download"),
            pytest.param(
                "run/with spaces & $pecial",
                "run_with_spaces____pecial",
                id="special-characters-replaced",
            ),
        ],
    )
    def test_normalization_contract(self, input_name: str, expected: str) -> None:
        assert _safe_filename(input_name) == expected

    def test_long_name_truncated(self) -> None:
        result = _safe_filename("a" * 500)
        assert result == "a" * 200
