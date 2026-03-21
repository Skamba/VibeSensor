"""Internal parsing helpers shared by snapshot value-object modules."""

from __future__ import annotations

import math
from collections.abc import Mapping

from ._numeric import coerce_float


def _float_or(d: Mapping[str, object], key: str, default: float = 0.0) -> float:
    v = d.get(key)
    if v is None:
        return default
    try:
        f = coerce_float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _bool_or(d: Mapping[str, object], key: str, default: bool = False) -> bool:  # noqa: FBT001, FBT002
    v = d.get(key)
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return default


def _int_or(d: Mapping[str, object], key: str, default: int = 0) -> int:
    v = d.get(key)
    if v is None:
        return default
    if isinstance(v, (int, float, str)):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default
    return default


def _str_or(d: Mapping[str, object], key: str, default: str = "") -> str:
    v = d.get(key)
    if v is None:
        return default
    return str(v)


def _opt_str(d: Mapping[str, object], key: str) -> str | None:
    v = d.get(key)
    if v is None:
        return None
    return str(v)


def _opt_float_raw(d: Mapping[str, object], key: str) -> float | None:
    v = d.get(key)
    if v is None:
        return None
    try:
        f = coerce_float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None
