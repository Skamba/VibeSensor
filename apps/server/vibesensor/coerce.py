"""Type-safe numeric coercion for boundary deserialization.

``coerce_float`` and ``coerce_int`` accept ``object`` input and narrow
via ``isinstance`` so mypy validates the call without ``type: ignore``.
"""

from __future__ import annotations

__all__ = ["coerce_float", "coerce_int"]


def coerce_float(value: object) -> float:
    """Coerce an untrusted ``object`` to ``float`` without ``type: ignore``.

    Narrows via ``isinstance`` so the call is statically valid for mypy.
    Raises ``TypeError`` or ``ValueError`` on non-numeric input — callers
    must handle those when the source is untrusted.
    """
    if isinstance(value, (int, float, str, bytes)):
        return float(value)
    raise TypeError(f"Cannot coerce {type(value).__name__} to float")


def coerce_int(value: object) -> int:
    """Coerce an untrusted ``object`` to ``int`` without ``type: ignore``.

    Uses ``round()`` on the float conversion for fractional values.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return round(coerce_float(value))
