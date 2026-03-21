"""Domain-owned numeric coercion helpers for tolerant mapping parsers."""

from __future__ import annotations

__all__ = ["coerce_float", "coerce_int"]


def coerce_float(value: object) -> float:
    """Coerce an untrusted ``object`` to ``float`` for domain factories.

    Domain value-object factories still parse persisted/runtime mappings, so they
    need a local helper instead of importing the root shared utility layer.
    Raises ``TypeError`` or ``ValueError`` on non-numeric input.
    """
    if isinstance(value, (int, float, str, bytes)):
        return float(value)
    raise TypeError(f"Cannot coerce {type(value).__name__} to float")


def coerce_int(value: object) -> int:
    """Coerce an untrusted ``object`` to ``int`` using rounded float parsing."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return round(coerce_float(value))
