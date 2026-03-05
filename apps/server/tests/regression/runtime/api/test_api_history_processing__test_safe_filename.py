"""Runtime regressions spanning API, history, and processing boundaries."""

from __future__ import annotations

import re

import pytest

from vibesensor.api import _safe_filename

_SAFE_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


class TestSafeFilename:
    """Ensure _safe_filename strips dangerous characters for HTTP headers."""

    def test_normal_run_id_unchanged(self) -> None:
        assert _safe_filename("run-2026-01-15_12-30") == "run-2026-01-15_12-30"

    @pytest.mark.parametrize(
        "raw,forbidden",
        [
            ('run"injected', ['"']),
            ("run\r\nX-Injected: yes", ["\r", "\n"]),
            ("../../etc/passwd", ["/", "\\"]),
        ],
        ids=["double-quotes", "crlf", "path-separators"],
    )
    def test_dangerous_chars_stripped(self, raw: str, forbidden: list[str]) -> None:
        result = _safe_filename(raw)
        for ch in forbidden:
            assert ch not in result

    def test_empty_input_returns_download(self) -> None:
        assert _safe_filename("") == "download"

    def test_only_special_chars_returns_underscores(self) -> None:
        result = _safe_filename('""///')
        assert result  # non-empty
        assert '"' not in result
        assert "/" not in result

    def test_long_input_truncated(self) -> None:
        assert len(_safe_filename("a" * 300)) <= 200

    @pytest.mark.parametrize("raw", ["normal-run", "run 123", "run<script>", "run;echo hi"])
    def test_result_matches_safe_pattern(self, raw: str) -> None:
        result = _safe_filename(raw)
        assert _SAFE_RE.match(result), f"Unsafe chars in result: {result!r}"
