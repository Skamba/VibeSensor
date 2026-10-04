"""UTC timestamp parsing, formatting and recorded-timezone helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vibesensor.common.time_utils import (
    coerce_utc_offset_seconds,
    format_run_timestamp,
    format_timestamp_in_recorded_timezone,
    format_utc_timestamp,
    parse_iso8601,
    utc_now_iso,
)

# -- utc_now_iso ---------------------------------------------------------------


def test_utc_now_iso_round_trips_as_an_aware_timestamp() -> None:
    parsed = parse_iso8601(utc_now_iso())
    assert parsed is not None
    assert parsed.utcoffset() is not None


# -- parse_iso8601 ------------------------------------------------------------


@pytest.mark.parametrize("value", ["2025-01-15T10:30:00+00:00", "2025-01-15T10:30:00Z"])
def test_parse_iso8601_accepts_offset_and_z_suffix(value: str) -> None:
    assert parse_iso8601(value) == datetime(2025, 1, 15, 10, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "value",
    [None, "", "   ", "not-a-date", 12345, 3.14],
    ids=["none", "empty", "whitespace", "invalid-str", "int", "float"],
)
def test_parse_iso8601_returns_none_for_bad_input(value: object) -> None:
    assert parse_iso8601(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2025-01-15T10:30:00Z", "2025-01-15 10:30:00 UTC"),
        ("2025-01-15T12:30:00+02:00", "2025-01-15 10:30:00 UTC"),
        ("2025-01-15 10:30:00", "2025-01-15 10:30:00 UTC"),
        ("not-a-date", "not-a-date"),
        ("", None),
        (None, None),
    ],
)
def test_format_utc_timestamp(value: object, expected: str | None) -> None:
    assert format_utc_timestamp(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (7200, 7200),
        ("7200", 7200),
        (-19800, -19800),
        (None, None),
        ("bad", None),
        (14 * 60 * 60, 14 * 60 * 60),
        (-12 * 60 * 60, -12 * 60 * 60),
        (15 * 60 * 60, None),
        (True, None),
    ],
)
def test_coerce_utc_offset_seconds(value: object, expected: int | None) -> None:
    assert coerce_utc_offset_seconds(value) == expected


@pytest.mark.parametrize(
    ("value", "recorded_utc_offset_seconds", "expected"),
    [
        ("2025-01-15T10:30:00Z", 7200, "2025-01-15 12:30:00 UTC+02:00"),
        ("2025-01-15T10:30:00Z", -19800, "2025-01-15 05:00:00 UTC-05:30"),
        ("2025-01-15 10:30:00", 7200, "2025-01-15 12:30:00 UTC+02:00"),
        ("2025-01-15T10:30:00Z", None, "2025-01-15 10:30:00 UTC"),
        ("not-a-date", 7200, "not-a-date"),
        ("", 7200, None),
        (None, 7200, None),
    ],
)
def test_format_timestamp_in_recorded_timezone(
    value: object,
    recorded_utc_offset_seconds: object,
    expected: str | None,
) -> None:
    assert format_timestamp_in_recorded_timezone(value, recorded_utc_offset_seconds) == expected


@pytest.mark.parametrize(
    ("value", "time_zone", "expected"),
    [
        # The user's zone wins over the offset stored with the run (the image default),
        # and is taken at the run's own instant: summer and winter differ.
        ("2025-07-01T10:00:00Z", "Europe/Amsterdam", "2025-07-01 12:00:00 UTC+02:00"),
        ("2025-01-15T10:00:00Z", "Europe/Amsterdam", "2025-01-15 11:00:00 UTC+01:00"),
        # No (or an unknown) zone: fall back to the stored offset.
        ("2025-07-01T10:00:00Z", None, "2025-07-01 13:00:00 UTC+03:00"),
        ("2025-07-01T10:00:00Z", "Mars/Olympus_Mons", "2025-07-01 13:00:00 UTC+03:00"),
        (None, "Europe/Amsterdam", None),
    ],
)
def test_format_run_timestamp_prefers_the_users_zone(
    value: str | None, time_zone: str | None, expected: str | None
) -> None:
    assert (
        format_run_timestamp(value, time_zone=time_zone, recorded_utc_offset_seconds=10800)
        == expected
    )
