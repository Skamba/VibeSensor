"""Shared scalar coercion helpers for boundary codecs."""

from __future__ import annotations

from vibesensor.shared.json_utils import as_float_or_none, as_int_or_none

__all__ = ["coerce_count", "float_or", "optional_float", "text_or_none"]


def text_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def optional_float(value: object) -> float | None:
    return as_float_or_none(value)


def float_or(value: object, default: float = 0.0) -> float:
    parsed = as_float_or_none(value)
    return parsed if parsed is not None else default


def coerce_count(value: object) -> int:
    parsed = as_int_or_none(value)
    return parsed if parsed is not None else 0
