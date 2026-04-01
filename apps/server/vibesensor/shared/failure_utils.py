"""Shared failure-message normalization helpers."""

from __future__ import annotations

__all__ = ["bounded_failure_message"]


def bounded_failure_message(exc: BaseException, *, max_length: int = 240) -> str:
    """Normalize an exception into a bounded, non-empty operator-facing message."""

    message = str(exc).strip() or exc.__class__.__name__
    if max_length <= 0 or len(message) <= max_length:
        return message
    if max_length <= 3:
        return message[:max_length]
    return f"{message[: max_length - 3]}..."
