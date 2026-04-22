"""UDP transport startup and cleanup lifecycle for the runtime."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

__all__ = ["StartUdpReceiver", "UdpTransportLifecycle"]


class UdpQueueConsumer(Protocol):
    async def process_queue(self) -> None: ...


StartUdpReceiver = Callable[
    ...,
    Awaitable[tuple[asyncio.DatagramTransport | None, UdpQueueConsumer | None]],
]
StartBackgroundTask = Callable[[Callable[[], Awaitable[object]]], None]


class UdpTransportLifecycle:
    """Own the UDP receiver transport and consumer-task lifecycle."""

    __slots__ = (
        "_data_transport",
        "_logger",
        "_start_background_task",
        "_start_udp_receiver",
    )

    def __init__(
        self,
        *,
        start_udp_receiver: StartUdpReceiver,
        start_background_task: StartBackgroundTask,
        logger: logging.Logger,
    ) -> None:
        self._start_udp_receiver = start_udp_receiver
        self._start_background_task = start_background_task
        self._logger = logger
        self._data_transport: asyncio.DatagramTransport | None = None

    @property
    def transport(self) -> asyncio.DatagramTransport | None:
        return self._data_transport

    async def startup(
        self,
        *,
        host: str,
        port: int,
        registry: object,
        processor: object,
        raw_capture_sink: object | None = None,
        queue_maxsize: int,
    ) -> None:
        self._data_transport, consumer = await self._start_udp_receiver(
            host=host,
            port=port,
            registry=registry,
            processor=processor,
            raw_capture_sink=raw_capture_sink,
            queue_maxsize=queue_maxsize,
        )
        if consumer is not None:
            self._start_background_task(consumer.process_queue)

    async def shutdown(self) -> None:
        try:
            if self._data_transport is not None:
                self._data_transport.close()
                self._data_transport = None
        except OSError:
            self._logger.warning("Error closing data transport", exc_info=True)
