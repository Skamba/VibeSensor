from __future__ import annotations

import asyncio
import time
from collections.abc import Callable


def wait_until(
    predicate: Callable[[], object], timeout_s: float = 2.0, step_s: float = 0.02
) -> bool:
    """Poll *predicate* until it returns truthy, or *timeout_s* expires."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step_s)
    return False


async def async_wait_until(
    predicate: Callable[[], object], timeout_s: float = 2.0, step_s: float = 0.02
) -> bool:
    """Async version of wait_until; yields to the event loop between polls."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(step_s)
    return False
