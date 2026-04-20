"""BroadcastTickController coverage for tick flow, warnings, and backoff."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import patch

import pytest

from vibesensor.adapters.websocket.tick_controller import (
    BroadcastTickController,
    BroadcastTickLoopFailure,
)


@pytest.mark.asyncio
async def test_controller_calls_on_tick_and_broadcast() -> None:
    controller = BroadcastTickController(
        hz=1000,
        logger=logging.getLogger("vibesensor.adapters.websocket.hub"),
    )
    tick_count = 0
    broadcast_count = 0

    def on_tick() -> None:
        nonlocal tick_count
        tick_count += 1

    async def broadcast_tick() -> None:
        nonlocal broadcast_count
        broadcast_count += 1
        if broadcast_count >= 3:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await controller.run(broadcast_tick=broadcast_tick, on_tick=on_tick)

    assert tick_count == 3
    assert broadcast_count == 3


@pytest.mark.asyncio
async def test_controller_on_tick_exception_propagates() -> None:
    logger = logging.getLogger("vibesensor.adapters.websocket.hub")
    controller = BroadcastTickController(hz=1000, logger=logger)
    tick_count = 0

    def on_tick() -> None:
        nonlocal tick_count
        tick_count += 1
        if tick_count == 1:
            raise RuntimeError("tick fail")

    async def broadcast_tick() -> None:
        raise AssertionError("broadcast should not run after on_tick failure")

    with pytest.raises(RuntimeError, match="tick fail"):
        await controller.run(broadcast_tick=broadcast_tick, on_tick=on_tick)


@pytest.mark.asyncio
async def test_controller_escalates_after_consecutive_failures(caplog) -> None:
    logger = logging.getLogger("vibesensor.adapters.websocket.hub")
    controller = BroadcastTickController(
        hz=10,
        logger=logger,
        max_consecutive_failures=2,
    )
    sleep_calls: list[float] = []
    original_sleep = asyncio.sleep

    async def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)
        await original_sleep(0)

    async def failing_broadcast() -> None:
        raise OSError("boom")

    with (
        patch(
            "vibesensor.adapters.websocket.tick_controller.anyio.sleep",
            side_effect=fake_sleep,
        ),
        caplog.at_level(logging.WARNING, logger="vibesensor.adapters.websocket.hub"),
        pytest.raises(BroadcastTickLoopFailure, match="2 consecutive times"),
    ):
        await controller.run(broadcast_tick=failing_broadcast)

    assert sleep_calls == [pytest.approx(0.1, rel=0.2)]
    assert any("1 consecutive" in record.message for record in caplog.records)
    assert any("2 consecutive times; escalating." in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_controller_clamps_hz_to_minimum_one(caplog) -> None:
    logger = logging.getLogger("vibesensor.adapters.websocket.hub")
    controller = BroadcastTickController(hz=0, logger=logger)
    sleep_calls: list[float] = []

    async def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)
        raise asyncio.CancelledError

    async def broadcast_tick() -> None:
        return None

    with (
        patch(
            "vibesensor.adapters.websocket.tick_controller.anyio.sleep",
            side_effect=fake_sleep,
        ),
        caplog.at_level(logging.WARNING, logger="vibesensor.adapters.websocket.hub"),
        pytest.raises(asyncio.CancelledError),
    ):
        await controller.run(broadcast_tick=broadcast_tick)

    assert sleep_calls == [pytest.approx(1.0, rel=0.05)]
    assert any("clamping to 1 Hz" in record.message for record in caplog.records)
