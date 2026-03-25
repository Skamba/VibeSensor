"""Broadcast tick scheduling and backoff control for WebSocket run loops."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

__all__ = ["BroadcastTickController"]

_MAX_CONSECUTIVE_FAILURES: int = 10
_BACKOFF_MULTIPLIER: int = 5


class BroadcastTickController:
    """Drive a broadcast loop with fixed-rate timing and failure backoff."""

    def __init__(
        self,
        *,
        hz: int,
        logger: logging.Logger,
        max_consecutive_failures: int = _MAX_CONSECUTIVE_FAILURES,
        backoff_multiplier: int = _BACKOFF_MULTIPLIER,
    ) -> None:
        if hz <= 0:
            logger.warning(
                "WebSocketHub.run called with hz=%r; clamping to 1 Hz.",
                hz,
            )
        self._logger = logger
        self._interval = 1.0 / max(1, hz)
        self._max_consecutive_failures = max_consecutive_failures
        self._backoff_multiplier = backoff_multiplier

    async def run(
        self,
        *,
        broadcast_tick: Callable[[], Awaitable[None]],
        on_tick: Callable[[], None] | None = None,
    ) -> None:
        """Drive the loop until cancelled, preserving existing retry behavior."""

        consecutive_failures = 0
        loop = asyncio.get_running_loop()
        while True:
            tick_start = loop.time()
            try:
                if on_tick is not None:
                    try:
                        on_tick()
                    except Exception:
                        self._logger.warning(
                            "WebSocket on_tick callback raised; proceeding to broadcast.",
                            exc_info=True,
                        )
                await broadcast_tick()
                consecutive_failures = 0
            except Exception:
                consecutive_failures += 1
                if consecutive_failures >= self._max_consecutive_failures:
                    self._logger.error(
                        "WebSocket broadcast tick failed %d consecutive times; backing off.",
                        consecutive_failures,
                        exc_info=True,
                    )
                    await asyncio.sleep(self._interval * self._backoff_multiplier)
                    tick_start = loop.time()
                    consecutive_failures = 0
                else:
                    self._logger.warning(
                        "WebSocket broadcast tick failed (%d consecutive); will retry.",
                        consecutive_failures,
                        exc_info=True,
                    )
            elapsed = loop.time() - tick_start
            await asyncio.sleep(max(0, self._interval - elapsed))
