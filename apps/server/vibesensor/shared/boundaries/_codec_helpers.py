"""Shared scalar coercion helpers for boundary codecs."""

from __future__ import annotations

from vibesensor.domain import coerce_float, coerce_int

__all__ = ["coerce_count", "optional_float", "text_or_none"]


def text_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return coerce_float(value)
    except (TypeError, ValueError):
        return None


def coerce_count(value: object) -> int:
    if value is None:
        return 0
    try:
        return coerce_int(value)
    except (TypeError, ValueError):
        return 0
