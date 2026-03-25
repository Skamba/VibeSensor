"""UDP transport startup and cleanup lifecycle for the runtime."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine

__all__ = ["StartUdpReceiver", "UdpTransportLifecycle"]

StartUdpReceiver = Callable[
    ...,
    Coroutine[
        object,
        object,
        tuple[asyncio.DatagramTransport | None, asyncio.Task[object] | None],
    ],
]
MonitorTask = Callable[[asyncio.Task[object]], None]


class UdpTransportLifecycle:
    """Own the UDP receiver transport and consumer-task lifecycle."""

    __slots__ = (
        "_data_consumer_task",
        "_data_transport",
        "_logger",
        "_monitor_task",
        "_start_udp_receiver",
    )

    def __init__(
        self,
        *,
        start_udp_receiver: StartUdpReceiver,
        monitor_task: MonitorTask,
        logger: logging.Logger,
    ) -> None:
        self._start_udp_receiver = start_udp_receiver
        self._monitor_task = monitor_task
        self._logger = logger
        self._data_transport: asyncio.DatagramTransport | None = None
        self._data_consumer_task: asyncio.Task[object] | None = None

    @property
    def consumer_task(self) -> asyncio.Task[object] | None:
        return self._data_consumer_task

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
        queue_maxsize: int,
    ) -> None:
        self._data_transport, self._data_consumer_task = await self._start_udp_receiver(
            host=host,
            port=port,
            registry=registry,
            processor=processor,
            queue_maxsize=queue_maxsize,
        )
        if self._data_consumer_task is not None:
            self._monitor_task(self._data_consumer_task)

    async def shutdown(self) -> None:
        try:
            if self._data_transport is not None:
                self._data_transport.close()
                self._data_transport = None
        except OSError:
            self._logger.warning("Error closing data transport", exc_info=True)
        if self._data_consumer_task is not None:
            self._data_consumer_task.cancel()
            await asyncio.gather(self._data_consumer_task, return_exceptions=True)
            self._data_consumer_task = None
