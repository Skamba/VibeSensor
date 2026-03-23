"""Shared typing helpers used in runtime coercion paths."""

from __future__ import annotations

from typing import Final

NUMERIC_TYPES: Final = (int, float)
"""Cached type-tuple for ``isinstance`` checks against numeric types.

The annotation is left to inference (``tuple[type[int], type[float]]``) so
that mypy can narrow ``isinstance(x, NUMERIC_TYPES)`` to ``int | float``.
"""
