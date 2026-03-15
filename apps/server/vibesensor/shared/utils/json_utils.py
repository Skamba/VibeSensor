"""Shared JSON sanitisation, merging, and coercion utilities.

Provides numpy-aware non-finite-float sanitisation and recursive
dict-merge used across config loading, WebSocket hub, and history.
"""

from __future__ import annotations

import json
import logging
import math

from vibesensor.shared.types.json import JsonObject, JsonValue, is_json_object

__all__ = [
    "as_float_or_none",
    "as_int_or_none",
    "deep_merge",
    "safe_json_dumps",
    "safe_json_loads",
    "sanitize_for_json",
    "sanitize_value",
]

_isfinite = math.isfinite


def as_float_or_none(value: object) -> float | None:
    """Return *value* as a finite float, or ``None`` for non-numeric / non-finite input."""
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not _isfinite(out):
        return None
    return out


def as_int_or_none(value: object) -> int | None:
    """Return *value* as a rounded int, or ``None`` for non-numeric / non-finite input."""
    out = as_float_or_none(value)
    if out is None:
        return None
    return round(out)


LOGGER = logging.getLogger(__name__)


def sanitize_for_json(obj: object, *, _max_depth: int = 128) -> tuple[object, bool]:
    """Recursively replace non-finite floats (NaN, Inf, -Inf) with ``None``.

    Numpy arrays are converted to Python lists and numpy scalars to native
    Python types so the result is always plain-Python and serialisable with
    ``json.dumps(allow_nan=False)``.

    Returns the sanitised object and a boolean flag indicating whether any
    non-finite value was encountered.
    """
    found_non_finite = False
    _isfinite = math.isfinite  # local binding avoids module lookup per call

    def _walk(v: object, depth: int = 0) -> object:
        nonlocal found_non_finite
        if depth > _max_depth:
            LOGGER.warning(
                "sanitize_for_json: nesting depth %d exceeded limit %d; truncating to None",
                depth,
                _max_depth,
            )
            return None
        # Fast path: common leaf types that never need sanitisation.
        # Intentional type() identity checks (not isinstance): these are exact
        # native Python types with no relevant subclasses in our payloads, and
        # skipping isinstance() avoids its hasattr/MRO probes on the hot path.
        t = type(v)
        if t is int or t is str or t is bool or v is None:
            return v
        # Numpy array -> Python list (check ndim to distinguish from scalars).
        if hasattr(v, "tolist") and hasattr(v, "ndim"):
            v = v.tolist()
            t = type(v)
        # Numpy scalar -> native Python type via .item().
        elif hasattr(v, "item"):
            v = v.item()
            t = type(v)
        if t is float:
            if _isfinite(v):  # type: ignore[arg-type]
                return v
            found_non_finite = True
            return None
        if isinstance(v, dict):
            return {k: _walk(val, depth + 1) for k, val in v.items()}
        if isinstance(v, (list, tuple)):
            return [_walk(item, depth + 1) for item in v]
        return v

    cleaned = _walk(obj)
    return cleaned, found_non_finite


def sanitize_value(value: object) -> object:
    """Sanitise *value* for JSON, discarding the non-finite flag.

    Convenience wrapper around :func:`sanitize_for_json` for callers that
    only need the cleaned value (e.g. database serialisation).
    """
    cleaned, _ = sanitize_for_json(value)
    return cleaned


def safe_json_dumps(value: object) -> str:
    """Sanitise *value* and serialise to a compact JSON string.

    Combines :func:`sanitize_value` with ``json.dumps`` using safe
    defaults (``allow_nan=False``, ``ensure_ascii=False``).
    """
    return json.dumps(sanitize_value(value), ensure_ascii=False, allow_nan=False)


def safe_json_loads(value: str | None, *, context: str) -> JsonValue | None:
    """Deserialise a JSON string, returning ``None`` on empty/invalid input.

    Logs a warning (with traceback) instead of raising on malformed JSON,
    making it safe for reading persisted data that may have been corrupted.

    *context* is included in the warning message to identify the source::

        safe_json_loads(raw, context="run abc123 metadata")
    """
    if not value:
        return None
    try:
        return json.loads(value)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        LOGGER.warning("Skipping invalid JSON payload while reading %s", context, exc_info=True)
        return None


def deep_merge(base: JsonObject, override: JsonObject) -> JsonObject:
    """Recursively merge *override* into *base* (new dict, no mutation).

    - Nested dicts are merged recursively.
    - ``None`` overrides for existing dict sections are logged and skipped
      (YAML ``key:`` with no value produces ``None``).
    - Scalar/list values in *override* replace the *base* value.
    """
    merged: JsonObject = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if is_json_object(value) and is_json_object(existing):
            merged[key] = deep_merge(existing, value)
        elif value is None and is_json_object(existing):
            LOGGER.warning(
                "Config key %r is null; keeping default section. "
                "Did you mean to leave the section empty?",
                key,
            )
        else:
            merged[key] = value
    return merged
