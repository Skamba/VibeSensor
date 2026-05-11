"""Assertion helpers for processing fuzz targets."""

from __future__ import annotations

import json
from collections.abc import Sequence


def json_no_nan(value: object) -> None:
    json.dumps(value, ensure_ascii=False, allow_nan=False)


def is_sorted_desc(values: Sequence[float]) -> bool:
    return all(left >= right for left, right in zip(values, values[1:], strict=False))
