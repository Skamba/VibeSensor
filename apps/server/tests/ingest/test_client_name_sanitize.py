"""Sensor names drop control characters and fit the protocol's 32 UTF-8 bytes."""

from __future__ import annotations

import pytest

from vibesensor.ingest.client_metadata import sanitize_client_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Hello", "Hello"),
        ("A" * 32, "A" * 32),
        ("A" * 33, "A" * 32),
        # Each euro sign is 3 bytes: 11 of them (33 bytes) are cut to 10, never mid-character.
        ("€" * 11, "€" * 10),
        ("hel\x00lo", "hello"),
        ("\x01\x02\x03", ""),
    ],
    ids=["ascii", "exactly-32-bytes", "33-bytes", "multibyte", "control-chars", "only-controls"],
)
def test_sanitize_client_name(raw: str, expected: str) -> None:
    assert sanitize_client_name(raw) == expected
