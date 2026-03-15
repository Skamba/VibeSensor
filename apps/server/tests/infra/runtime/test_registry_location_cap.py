"""Regression tests for ClientRegistry.set_location 64-byte cap — Jack3 fixes.

Prior to the fix, set_location accepted arbitrarily long strings, which could
bloat in-memory records and cause storage issues.  The fix caps at 64 UTF-8 bytes
without splitting multi-byte characters.

These tests are written to catch any regression of that capping logic.
"""

from __future__ import annotations

from pathlib import Path

from vibesensor.adapters.persistence.history_db import HistoryDB
from vibesensor.infra.runtime.registry import ClientRegistry

_CLIENT_ID = "aabbccddeeff"


def _make_registry(tmp_path: Path) -> ClientRegistry:
    db = HistoryDB(tmp_path / "history.db")
    return ClientRegistry(db=db)


# ── Location cap at 64 bytes ──────────────────────────────────────────────────


def test_set_location_short_string_preserved(tmp_path: Path) -> None:
    """A short location label is stored verbatim."""
    registry = _make_registry(tmp_path)
    record = registry.set_location(_CLIENT_ID, "front-left")
    assert record.location_code == "front-left"


def test_set_location_exactly_64_ascii_bytes_preserved(tmp_path: Path) -> None:
    """A location string that is exactly 64 ASCII bytes is not truncated."""
    label = "x" * 64  # 64 bytes in UTF-8 (all ASCII)
    registry = _make_registry(tmp_path)
    record = registry.set_location(_CLIENT_ID, label)
    assert len(record.location_code.encode("utf-8")) == 64
    assert record.location_code == label


def test_set_location_over_64_ascii_bytes_capped(tmp_path: Path) -> None:
    """A location string exceeding 64 ASCII bytes is truncated to 64 bytes."""
    label = "a" * 100  # 100 bytes in UTF-8
    registry = _make_registry(tmp_path)
    record = registry.set_location(_CLIENT_ID, label)
    encoded = record.location_code.encode("utf-8")
    assert len(encoded) <= 64


def test_set_location_multibyte_truncation_safe(tmp_path: Path) -> None:
    """Multi-byte characters are not split mid-codepoint during truncation.

    A naive [:64] slice on the raw UTF-8 bytes could leave a partial sequence.
    The registry must decode back cleanly after truncation.
    """
    # Each '€' is 3 bytes.  25 × '€' = 75 bytes → must be truncated.
    label = "€" * 25
    registry = _make_registry(tmp_path)
    record = registry.set_location(_CLIENT_ID, label)
    # Must be valid UTF-8 (no UnicodeDecodeError)
    encoded = record.location_code.encode("utf-8")
    assert len(encoded) <= 64
    # Must decode cleanly (round-trip)
    assert encoded.decode("utf-8") == record.location_code


def test_set_location_strips_whitespace_before_cap(tmp_path: Path) -> None:
    """Leading/trailing whitespace is stripped before the 64-byte cap is applied."""
    padded = "  front-left  "
    registry = _make_registry(tmp_path)
    record = registry.set_location(_CLIENT_ID, padded)
    assert record.location_code == "front-left"


def test_set_location_empty_string_stored(tmp_path: Path) -> None:
    """An empty location (after stripping) is accepted and stored."""
    registry = _make_registry(tmp_path)
    record = registry.set_location(_CLIENT_ID, "")
    assert record.location_code == ""


def test_set_location_visible_on_snapshot(tmp_path: Path) -> None:
    """The location is visible in the registry snapshot after set_location."""
    registry = _make_registry(tmp_path)
    registry.set_location(_CLIENT_ID, "rear-right")
    snapshot = registry.snapshot_for_api(now=1.0)
    matched = [s for s in snapshot if s.get("id") == _CLIENT_ID]
    assert matched, "client_id not found in snapshot"
    assert matched[0].get("location_code") == "rear-right"


# ── _resolve_now_mono: provided value must not be shadowed ───────────────────


def test_resolve_now_mono_returns_provided_value() -> None:
    """_resolve_now_mono must return the provided float, not call time.monotonic().

    Before the Jack3 refactor, a name-shadowing bug could cause the injected
    `now_mono` kwarg to be overridden by a fresh time.monotonic() call, making
    deterministic test injection impossible.
    """
    pinned = 42.0
    result = ClientRegistry._resolve_now_mono(pinned)
    assert result == pinned


def test_resolve_now_mono_none_returns_monotonic_like_value() -> None:
    """_resolve_now_mono(None) must return a positive float (real monotonic time)."""
    import time

    before = time.monotonic()
    result = ClientRegistry._resolve_now_mono(None)
    after = time.monotonic()
    assert isinstance(result, float)
    assert before <= result <= after
