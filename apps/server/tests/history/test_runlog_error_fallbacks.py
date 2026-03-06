"""Tests for append_jsonl_records NaN/Inf fallback paths.

Regression suite verifying that non-finite floats (NaN, Infinity) are
sanitised to JSON null rather than written as bare NaN/Infinity literals
(which are not valid JSON and cannot be round-tripped via json.loads).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from vibesensor.runlog import append_jsonl_records

# -- Helpers -------------------------------------------------------------------


def _read_lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# -- NaN sanitization ----------------------------------------------------------


class TestNaNSanitization:
    """NaN in a record must be sanitised to null, not written as bare NaN."""

    def test_nan_sanitized_to_null_valid_json(self, tmp_path: Path) -> None:
        """A record with NaN must produce a valid JSON line parseable by json.loads."""
        path = tmp_path / "run.jsonl"
        record = {"type": "sample", "accel_x_g": float("nan"), "ts": 1.0}
        append_jsonl_records(path, [record])

        lines = _read_lines(path)
        assert len(lines) == 1, "Expected exactly one JSONL line"

        # Must be valid JSON — json.loads raises ValueError for bare NaN
        parsed = json.loads(lines[0])
        assert parsed["accel_x_g"] is None, "NaN should be serialised as null"
        assert parsed["ts"] == pytest.approx(1.0)

    def test_nan_record_does_not_contain_bare_nan_literal(self, tmp_path: Path) -> None:
        """The JSONL line must not contain the bare string NaN."""
        path = tmp_path / "run.jsonl"
        record = {"v": float("nan")}
        append_jsonl_records(path, [record])

        raw = path.read_text(encoding="utf-8")
        assert "NaN" not in raw, "Bare NaN literal must not appear in output"


# -- Inf sanitization ----------------------------------------------------------


class TestInfSanitization:
    """Infinity in a record must be sanitised to null."""

    def test_inf_record_written_as_null(self, tmp_path: Path) -> None:
        """A record with positive Infinity must produce null in the JSONL output."""
        path = tmp_path / "run.jsonl"
        record = {"type": "sample", "accel_z_g": math.inf, "ts": 2.0}
        append_jsonl_records(path, [record])

        lines = _read_lines(path)
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["accel_z_g"] is None, "Infinity should be serialised as null"

    def test_neg_inf_record_written_as_null(self, tmp_path: Path) -> None:
        """A record with negative Infinity must produce null in the JSONL output."""
        path = tmp_path / "run.jsonl"
        record = {"v": -math.inf}
        append_jsonl_records(path, [record])

        lines = _read_lines(path)
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["v"] is None

    def test_inf_record_does_not_contain_bare_infinity_literal(self, tmp_path: Path) -> None:
        """The JSONL line must not contain the bare string Infinity."""
        path = tmp_path / "run.jsonl"
        record = {"v": math.inf}
        append_jsonl_records(path, [record])

        raw = path.read_text(encoding="utf-8")
        assert "Infinity" not in raw, "Bare Infinity literal must not appear in output"


# -- Mixed batch ---------------------------------------------------------------


class TestMixedBatch:
    """Batch with mixed valid and NaN records must write all lines as valid JSON."""

    def test_mixed_batch_all_lines_valid_json(self, tmp_path: Path) -> None:
        """Every line in a mixed batch must parse cleanly with json.loads."""
        path = tmp_path / "run.jsonl"
        records = [
            {"i": 0, "v": 1.5},
            {"i": 1, "v": float("nan")},
            {"i": 2, "v": math.inf},
            {"i": 3, "v": -math.inf},
            {"i": 4, "v": 0.0},
        ]
        append_jsonl_records(path, records)

        lines = _read_lines(path)
        assert len(lines) == 5
        for i, line in enumerate(lines):
            parsed = json.loads(line)  # must not raise
            assert parsed["i"] == i
        # NaN/Inf records should have null
        assert json.loads(lines[1])["v"] is None
        assert json.loads(lines[2])["v"] is None
        assert json.loads(lines[3])["v"] is None
        # Valid records retain their values
        assert json.loads(lines[0])["v"] == pytest.approx(1.5)
        assert json.loads(lines[4])["v"] == pytest.approx(0.0)
