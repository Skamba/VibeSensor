"""Verify UDP transport startup wiring and shutdown cleanup behavior."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.infra.runtime.udp_transport_lifecycle import UdpTransportLifecycle


class _FakeConsumer:
    async def process_queue(self) -> None:
        return None


@pytest.mark.asyncio
async def test_startup_tracks_transport_and_starts_consumer_task() -> None:
    consumer = _FakeConsumer()
    transport = MagicMock()
    start_background_task = MagicMock()
    start_udp_receiver = AsyncMock(return_value=(transport, consumer))
    lifecycle = UdpTransportLifecycle(
        start_udp_receiver=start_udp_receiver,
        start_background_task=start_background_task,
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
    start_background_task.assert_called_once()
    task_factory = start_background_task.call_args.args[0]
    assert getattr(task_factory, "__self__", None) is consumer
    assert getattr(task_factory, "__name__", "") == "process_queue"


@pytest.mark.asyncio
async def test_shutdown_closes_transport() -> None:
    transport = MagicMock()
    lifecycle = UdpTransportLifecycle(
        start_udp_receiver=AsyncMock(return_value=(transport, None)),
        start_background_task=MagicMock(),
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
    )

    await lifecycle.startup(
        host="0.0.0.0",
        port=9000,
        registry=MagicMock(),
        processor=MagicMock(),
        queue_maxsize=64,
    )
    await lifecycle.shutdown()

    transport.close.assert_called_once_with()
    assert lifecycle.transport is None


@pytest.mark.asyncio
async def test_shutdown_logs_transport_close_error(caplog: pytest.LogCaptureFixture) -> None:
    transport = MagicMock()
    transport.close.side_effect = OSError("close boom")
    lifecycle = UdpTransportLifecycle(
        start_udp_receiver=AsyncMock(),
        start_background_task=MagicMock(),
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
        start_background_task=MagicMock(),
        logger=logging.getLogger("vibesensor.infra.runtime.lifecycle"),
    )

    await lifecycle.shutdown()

    assert lifecycle.transport is None
