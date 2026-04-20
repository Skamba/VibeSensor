"""Focused sync-to-async bridge for thread-owned or startup-time callers."""

from __future__ import annotations

import asyncio
import atexit
import threading
from collections.abc import Awaitable, Coroutine
from concurrent.futures import Future
from typing import cast

__all__ = ["run_coro_blocking"]


async def _await_result[T](awaitable: Awaitable[T]) -> T:
    return await awaitable


class _BridgeLoop:
    __slots__ = ("_loop", "_lock", "_ready", "_thread")

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None

    def run[T](self, awaitable: Awaitable[T]) -> T:
        loop = self._ensure_loop()
        coro: Coroutine[object, object, T]
        if asyncio.iscoroutine(awaitable):
            coro = cast(Coroutine[object, object, T], awaitable)
        else:
            coro = _await_result(awaitable)
        future: Future[T] = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()

    def close(self) -> None:
        loop = self._loop
        thread = self._thread
        if loop is None or thread is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=1.0)
        if loop.is_running():
            return
        loop.close()
        self._loop = None
        self._thread = None
        self._ready.clear()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        loop = self._loop
        if loop is not None:
            return loop
        with self._lock:
            loop = self._loop
            if loop is not None:
                return loop
            self._ready.clear()
            thread = threading.Thread(
                target=self._thread_main,
                name="run-coro-blocking-loop",
                daemon=True,
            )
            self._thread = thread
            thread.start()
            self._ready.wait()
            loop = self._loop
            if loop is None:
                raise RuntimeError("run_coro_blocking failed to start its background event loop")
            return loop

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        loop.run_forever()


_BRIDGE_LOOP = _BridgeLoop()
atexit.register(_BRIDGE_LOOP.close)


def run_coro_blocking[T](coro: Awaitable[T]) -> T:
    """Run *coro* to completion from a non-async caller.

    This helper is only valid from threads or startup-time code that do not
    already own a running event loop. It intentionally fails fast on the main
    async runtime thread so blocking persistence calls cannot sneak back into
    request handlers or other event-loop paths.
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _BRIDGE_LOOP.run(coro)
    raise RuntimeError("run_coro_blocking cannot be used from a running event loop")
