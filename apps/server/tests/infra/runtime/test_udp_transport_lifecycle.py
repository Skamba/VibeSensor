from __future__ import annotations

import asyncio
import contextlib
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.infra.runtime.udp_transport_lifecycle import UdpTransportLifecycle


@pytest.mark.asyncio
async def test_startup_tracks_transport_and_monitors_consumer_task() -> None:
    async def _consumer() -> None:
        await asyncio.Future()

    consumer = asyncio.create_task(_consumer(), name="udp-data-consumer")
    transport = MagicMock()
    monitor_task = MagicMock()
    start_udp_receiver = AsyncMock(return_value=(transport, consumer))
    lifecycle = UdpTransportLifecycle(
        start_udp_receiver=start_udp_receiver,
        monitor_task=monitor_task,
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
    )

    await lifecycle.startup(
        host="0.0.0.0",
        port=9000,
        registry=MagicMock(),
        processor=MagicMock(),
        queue_maxsize=64,
    )

    assert lifecycle.transport is transport
    assert lifecycle.consumer_task is consumer
    monitor_task.assert_called_once_with(consumer)

    await lifecycle.shutdown()
    with contextlib.suppress(asyncio.CancelledError):
        await consumer


@pytest.mark.asyncio
async def test_shutdown_closes_transport_and_cancels_consumer_task() -> None:
    cancelled = asyncio.Event()
    started = asyncio.Event()

    async def _consumer() -> None:
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    consumer = asyncio.create_task(_consumer(), name="udp-data-consumer")
    transport = MagicMock()
    lifecycle = UdpTransportLifecycle(
        start_udp_receiver=AsyncMock(return_value=(transport, consumer)),
        monitor_task=MagicMock(),
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
    )

    await lifecycle.startup(
        host="0.0.0.0",
        port=9000,
        registry=MagicMock(),
        processor=MagicMock(),
        queue_maxsize=64,
    )
    await asyncio.wait_for(started.wait(), timeout=1.0)
    await lifecycle.shutdown()
    await asyncio.wait_for(cancelled.wait(), timeout=1.0)

    transport.close.assert_called_once_with()
    assert lifecycle.transport is None
    assert lifecycle.consumer_task is None


@pytest.mark.asyncio
async def test_shutdown_logs_transport_close_error(caplog: pytest.LogCaptureFixture) -> None:
    transport = MagicMock()
    transport.close.side_effect = OSError("close boom")
    lifecycle = UdpTransportLifecycle(
        start_udp_receiver=AsyncMock(),
        monitor_task=MagicMock(),
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
    )
    lifecycle._data_transport = transport

    with caplog.at_level(logging.WARNING):
        await lifecycle.shutdown()

    assert "Error closing data transport" in caplog.text


@pytest.mark.asyncio
async def test_shutdown_without_started_transport_is_noop() -> None:
    lifecycle = UdpTransportLifecycle(
        start_udp_receiver=AsyncMock(),
        monitor_task=MagicMock(),
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
    )

    await lifecycle.shutdown()

    assert lifecycle.transport is None
    assert lifecycle.consumer_task is None
