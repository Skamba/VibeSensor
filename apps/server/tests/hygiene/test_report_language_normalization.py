"""Report language normalization accepts locale variants and falls back to English."""

from __future__ import annotations

import pytest

from vibesensor.report.i18n import normalize_lang


class TestNormalizeLangConsolidation:
    """Ensure normalize_lang is the canonical source and handles variants."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("en", "en"),
            ("nl", "nl"),
            ("nl-BE", "nl"),
            ("NL-NL", "nl"),
            ("  NL ", "nl"),
            ("nl_BE.UTF-8", "nl"),
            ("nld", "nl"),
            ("fr", "en"),
            ("en-US", "en"),
            (None, "en"),
            (42, "en"),
            ("", "en"),
        ],
    )
    def test_normalize_lang_handles_variants(self, raw: object, expected: str) -> None:
        assert normalize_lang(raw) == expected
