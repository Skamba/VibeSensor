"""Broadcast tick scheduling and failure escalation for WebSocket run loops."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import anyio

from vibesensor.shared.runtime_failures import BroadcastTickLoopFailure

__all__ = ["BroadcastTickController", "BroadcastTickLoopFailure"]

_MAX_CONSECUTIVE_FAILURES: int = 10
_RETRYABLE_BROADCAST_EXCEPTIONS = (OSError,)


class BroadcastTickController:
    """Drive a broadcast loop with fixed-rate timing and bounded local retries."""

    def __init__(
        self,
        *,
        hz: int,
        logger: logging.Logger,
        max_consecutive_failures: int = _MAX_CONSECUTIVE_FAILURES,
    ) -> None:
        if hz <= 0:
            logger.warning(
                "WebSocketHub.run called with hz=%r; clamping to 1 Hz.",
                hz,
            )
        self._logger = logger
        self._interval = 1.0 / max(1, hz)
        self._max_consecutive_failures = max_consecutive_failures

    async def run(
        self,
        *,
        broadcast_tick: Callable[[], Awaitable[None]],
        on_tick: Callable[[], None] | None = None,
    ) -> None:
        """Drive the loop until cancelled.

        Transient failures still retry inside the tick loop, but once the
        failure streak crosses the configured threshold this controller raises
        to the caller so runtime supervision can own restart/backoff policy and
        health reporting for the managed task.
        """

        consecutive_failures = 0
        while True:
            tick_start = anyio.current_time()
            if on_tick is not None:
                on_tick()
            try:
                await broadcast_tick()
                consecutive_failures = 0
            except _RETRYABLE_BROADCAST_EXCEPTIONS as exc:
                consecutive_failures += 1
                if consecutive_failures >= self._max_consecutive_failures:
                    self._logger.error(
                        "WebSocket broadcast tick failed %d consecutive times; escalating.",
                        consecutive_failures,
                        exc_info=True,
                    )
                    raise BroadcastTickLoopFailure(
                        consecutive_failures=consecutive_failures,
                        cause=exc,
                    ) from exc
                self._logger.warning(
                    "WebSocket broadcast tick failed (%d consecutive); will retry.",
                    consecutive_failures,
                    exc_info=True,
                )
            elapsed = anyio.current_time() - tick_start
            await anyio.sleep(max(0, self._interval - elapsed))
