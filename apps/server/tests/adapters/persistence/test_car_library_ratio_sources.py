"""Regression coverage for car-library ratio-source provenance hygiene."""

from __future__ import annotations

import json
from collections.abc import Iterator

from vibesensor.adapters.persistence.car_library import _DATA_FILE, load_car_library

_RATIO_SOURCES_FILE = _DATA_FILE.with_name("car_library_ratio_sources.json")
_PLACEHOLDER_PHRASE = "preserved pending official-source confirmation"
_ALLOWED_VERIFICATION_STATUSES = {
    "verification_backlog",
    "verified",
    "corrected",
    "intentionally_unsupported",
}
_TERMINAL_VERIFICATION_STATUSES = {
    "verified",
    "corrected",
    "intentionally_unsupported",
}
_LEGACY_AUDIT_PHRASES = (
    "fallback",
    "manual-review",
    "manual review",
    "wikipedia",
)
_LEGACY_SOURCE_KEYS = {
    "fallback_official_lookup",
    "second_pass_official_enrichment",
    "official_redo_lookup",
    "wikipedia_overview",
    "wikipedia_variant_tables",
}
_STATUS_SPOT_CHECKS = {
    "BMW|1 Series (F20, 2011-2019)": "verification_backlog",
    "BMW|2 Series Active Tourer (F45, 2014-2021)": "verification_backlog",
    "BMW|5 Series (G60, 2024-2026)": "corrected",
    "Audi|A4 (B9, 2016-2025)": "verification_backlog",
}


def _load_ratio_sources() -> dict[str, dict[str, object]]:
    with _RATIO_SOURCES_FILE.open() as fh:
        data = json.load(fh)
    return data["cars"]


def _car_key(entry: dict[str, object]) -> str:
    return f"{entry['brand']}|{entry['model']}"


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


def _list_field(entry: dict[str, object], key: str) -> list[object]:
    value = entry.get(key)
    return value if isinstance(value, list) else []


def test_car_library_ratio_sources_json_parseable() -> None:
    """The ratio-source JSON is valid and keeps the expected top-level shape."""
    cars = _load_ratio_sources()

    assert isinstance(cars, dict)
    assert cars, "Expected ratio-source metadata for at least one car"


def test_ratio_sources_do_not_contain_placeholder_preserved_notes() -> None:
    """Low-signal placeholder notes should not survive in ratio-source metadata."""
    data = _load_ratio_sources()

    offenders = [text for text in _walk_strings(data) if _PLACEHOLDER_PHRASE in text]
    assert offenders == []


def test_ratio_sources_all_rows_have_explicit_verification_status() -> None:
    data = _load_ratio_sources()

    for car_key, entry in data.items():
        status = entry.get("verification_status")
        assert status in _ALLOWED_VERIFICATION_STATUSES, (
            f"{car_key} missing valid verification_status: {status!r}"
        )


def test_ratio_sources_verification_backlog_rows_keep_explicit_unresolved_items() -> None:
    data = _load_ratio_sources()

    for car_key, entry in data.items():
        if entry.get("verification_status") != "verification_backlog":
            continue
        assert _list_field(entry, "unresolved"), (
            f"{car_key} must keep explicit unresolved items while verification backlog is open"
        )


def test_ratio_sources_terminal_rows_do_not_keep_unresolved_items() -> None:
    data = _load_ratio_sources()

    for car_key, entry in data.items():
        if entry.get("verification_status") not in _TERMINAL_VERIFICATION_STATUSES:
            continue
        assert _list_field(entry, "unresolved") == [], (
            f"{car_key} must move closed decisions out of unresolved once the row is terminal"
        )


def test_ratio_sources_intentionally_unsupported_rows_do_not_hide_pending_review() -> None:
    data = _load_ratio_sources()

    for car_key, entry in data.items():
        if entry.get("verification_status") != "intentionally_unsupported":
            continue
        summary = str(entry.get("decision_summary") or "").lower()
        assert "pending authoritative verification" not in summary, (
            f"{car_key} cannot be intentionally_unsupported while still pending verification"
        )
        assert _list_field(entry, "unresolved") == [], (
            f"{car_key} cannot be intentionally_unsupported "
            "while unresolved verification items remain"
        )


def test_ratio_sources_do_not_contain_legacy_audit_wording_or_keys() -> None:
    data = _load_ratio_sources()

    offenders = [
        text
        for text in _walk_strings(data)
        if any(phrase in text.lower() for phrase in _LEGACY_AUDIT_PHRASES)
    ]
    assert offenders == []

    legacy_source_keys = {
        car_key: sorted(set(entry.get("sources", {})) & _LEGACY_SOURCE_KEYS)
        for car_key, entry in data.items()
        if set(entry.get("sources", {})) & _LEGACY_SOURCE_KEYS
    }
    assert legacy_source_keys == {}


def test_ratio_sources_cover_every_car_library_row() -> None:
    ratio_source_keys = set(_load_ratio_sources())
    library_keys = {_car_key(entry) for entry in load_car_library()}
    assert ratio_source_keys == library_keys


def test_ratio_sources_status_spot_checks() -> None:
    data = _load_ratio_sources()

    observed = {car_key: data[car_key]["verification_status"] for car_key in _STATUS_SPOT_CHECKS}
    assert observed == _STATUS_SPOT_CHECKS
