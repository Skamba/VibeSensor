"""Assertion helpers for analysis fuzz targets."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def validate_summary(
    summary: Mapping[str, object],
    expected_rows: int,
    TypeAdapter: Any,
    AnalysisSummary: Any,
) -> None:
    TypeAdapter(AnalysisSummary).validate_python(summary)
    summary_rows = summary.get("rows")
    if summary_rows != expected_rows:
        raise AssertionError(
            f"summary rows {summary_rows!r} != expected {expected_rows}"
        )
    if summary.get("findings") is None:
        raise AssertionError("summary findings missing")
    if summary.get("run_suitability") is None:
        raise AssertionError("summary run_suitability missing")
    json.dumps(summary, ensure_ascii=False, allow_nan=False)
