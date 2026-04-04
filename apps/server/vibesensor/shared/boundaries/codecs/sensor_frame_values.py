"""Strict SensorFrame scalar validators shared by boundary adapters."""

from __future__ import annotations

import math

__all__ = [
    "SensorFrameDecodeError",
    "strict_optional_int",
    "strict_optional_float",
]


class SensorFrameDecodeError(ValueError):
    """Raised when a raw boundary sample cannot be decoded to ``SensorFrame``."""

    def __init__(self, *, source: str, field: str, detail: str) -> None:
        super().__init__(f"{source}: {field} {detail}")
        self.source = source
        self.field = field
        self.detail = detail


def strict_optional_float(value: object, *, field: str, source: str) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise SensorFrameDecodeError(
            source=source,
            field=field,
            detail="expected float-compatible value, got bool",
        )
    if not isinstance(value, int | float | str):
        raise SensorFrameDecodeError(
            source=source,
            field=field,
            detail=f"expected float-compatible value, got {type(value).__name__}",
        )
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise SensorFrameDecodeError(
            source=source,
            field=field,
            detail=f"expected float-compatible value, got {type(value).__name__}",
        ) from exc
    return numeric if math.isfinite(numeric) else None


def strict_optional_int(value: object, *, field: str, source: str) -> int | None:
    numeric = strict_optional_float(value, field=field, source=source)
    if numeric is None:
        return None
    if numeric.is_integer():
        return int(numeric)
    raise SensorFrameDecodeError(
        source=source,
        field=field,
        detail=f"expected integer-compatible value, got {numeric}",
    )
