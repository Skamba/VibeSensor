"""Operator-facing failure messages are non-empty and bounded."""

from __future__ import annotations

import pytest

from vibesensor.common.failure_utils import bounded_failure_message


@pytest.mark.parametrize(
    ("exc", "max_length", "expected"),
    [
        pytest.param(RuntimeError("  disk full  "), 240, "disk full", id="stripped"),
        pytest.param(RuntimeError(""), 240, "RuntimeError", id="empty-uses-class-name"),
        pytest.param(RuntimeError("x" * 300), 10, "xxxxxxx...", id="truncated-with-ellipsis"),
        pytest.param(RuntimeError("abcdef"), 3, "abc", id="tiny-limit-no-ellipsis"),
    ],
)
def test_bounded_failure_message(exc: BaseException, max_length: int, expected: str) -> None:
    assert bounded_failure_message(exc, max_length=max_length) == expected
