"""Regression coverage for car-library ratio-source provenance hygiene."""

from __future__ import annotations

import json
from collections.abc import Iterator

from vibesensor.adapters.persistence.car_library import _DATA_FILE

_RATIO_SOURCES_FILE = _DATA_FILE.with_name("car_library_ratio_sources.json")
_PLACEHOLDER_PHRASE = "preserved pending official-source confirmation"


def _walk_strings(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for nested in value.values():
            yield from _walk_strings(nested)
        return
    if isinstance(value, list):
        for nested in value:
            yield from _walk_strings(nested)
        return
    if isinstance(value, str):
        yield value


def test_car_library_ratio_sources_json_parseable() -> None:
    """The ratio-source JSON is valid and keeps the expected top-level shape."""
    with _RATIO_SOURCES_FILE.open() as fh:
        data = json.load(fh)

    assert isinstance(data, dict)
    assert isinstance(data.get("cars"), dict)
    assert data["cars"], "Expected ratio-source metadata for at least one car"


def test_ratio_sources_do_not_contain_placeholder_preserved_notes() -> None:
    """Low-signal placeholder notes should not survive in ratio-source metadata."""
    with _RATIO_SOURCES_FILE.open() as fh:
        data = json.load(fh)

    offenders = [text for text in _walk_strings(data) if _PLACEHOLDER_PHRASE in text]
    assert offenders == []
