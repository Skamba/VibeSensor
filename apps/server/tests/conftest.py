"""Shared test helpers for the vibesensor test suite."""

from __future__ import annotations

import time


def wait_until(predicate, timeout_s: float = 2.0, step_s: float = 0.02) -> bool:
    """Poll *predicate* until it returns truthy, or *timeout_s* expires."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step_s)
    return False
