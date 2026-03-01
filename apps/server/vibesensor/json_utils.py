"""Shared JSON sanitisation utilities.

Provides a single implementation of numpy-aware, non-finite-float
sanitisation used by both the WebSocket hub and the history database.
"""

from __future__ import annotations

import math
from typing import Any


def sanitize_for_json(obj: Any) -> tuple[Any, bool]:
    """Recursively replace non-finite floats (NaN, Inf, -Inf) with ``None``.

    Numpy arrays are converted to Python lists and numpy scalars to native
    Python types so the result is always plain-Python and serialisable with
    ``json.dumps(allow_nan=False)``.

    Returns the sanitised object and a boolean flag indicating whether any
    non-finite value was encountered.
    """
    found_non_finite = False

    def _walk(v: Any) -> Any:
        nonlocal found_non_finite
        # Numpy array → Python list (check ndim to distinguish from scalars).
        if hasattr(v, "tolist") and hasattr(v, "ndim"):
            v = v.tolist()
        # Numpy scalar → native Python type via .item().
        elif hasattr(v, "item"):
            v = v.item()
        if isinstance(v, float):
            if math.isfinite(v):
                return v
            found_non_finite = True
            return None
        if isinstance(v, dict):
            return {k: _walk(val) for k, val in v.items()}
        if isinstance(v, (list, tuple)):
            return [_walk(item) for item in v]
        return v

    cleaned = _walk(obj)
    return cleaned, found_non_finite


def sanitize_value(value: Any) -> Any:
    """Sanitise *value* for JSON, discarding the non-finite flag.

    Convenience wrapper around :func:`sanitize_for_json` for callers that
    only need the cleaned value (e.g. database serialisation).
    """
    cleaned, _ = sanitize_for_json(value)
    return cleaned
