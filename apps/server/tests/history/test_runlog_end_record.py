"""Unit tests for runlog.create_run_end_record.

create_run_end_record has no direct test coverage in the existing suite —
it is only exercised as part of append/read round-trips.  These tests pin
the function's output contract so regressions are caught immediately.
"""

from __future__ import annotations

from vibesensor.runlog import (
    RUN_END_TYPE,
    RUN_SCHEMA_VERSION,
    create_run_end_record,
    parse_iso8601,
)


class TestCreateRunEndRecord:
    """Direct unit tests for create_run_end_record output contract."""

    def test_record_type_is_run_end(self) -> None:
        """The 'record_type' field must equal the canonical RUN_END_TYPE constant."""
        rec = create_run_end_record("run-001")
        assert rec["record_type"] == RUN_END_TYPE

    def test_schema_version_is_included(self) -> None:
        """Record must carry the current schema version for backward-compat parsing."""
        rec = create_run_end_record("run-001")
        assert rec["schema_version"] == RUN_SCHEMA_VERSION

    def test_run_id_is_preserved(self) -> None:
        """The run_id provided by the caller must appear verbatim in the record."""
        rec = create_run_end_record("my-run-xyz-42")
        assert rec["run_id"] == "my-run-xyz-42"

    def test_explicit_end_time_is_used_verbatim(self) -> None:
        """When end_time_utc is supplied, the record must contain that exact value."""
        end_time = "2025-06-15T12:00:00+00:00"
        rec = create_run_end_record("run-001", end_time_utc=end_time)
        assert rec["end_time_utc"] == end_time

    def test_default_end_time_is_parseable_iso8601(self) -> None:
        """When end_time_utc is omitted, the fallback must be a valid UTC ISO-8601 string."""
        rec = create_run_end_record("run-002")
        end_time = rec.get("end_time_utc")
        assert end_time is not None
        parsed = parse_iso8601(end_time)
        assert parsed is not None, f"end_time_utc '{end_time}' is not parseable ISO-8601"

    def test_contains_only_expected_keys(self) -> None:
        """The record must not grow unexpected fields that could break parsers."""
        rec = create_run_end_record("run-003", end_time_utc="2025-01-01T00:00:00+00:00")
        expected_keys = {"record_type", "schema_version", "run_id", "end_time_utc"}
        assert set(rec.keys()) == expected_keys, (
            f"Unexpected record keys: {set(rec.keys()) - expected_keys}"
        )
