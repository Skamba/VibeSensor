from __future__ import annotations

import asyncio
import sys

import pytest

from vibesensor.simulator import sim_sender
from vibesensor.simulator.sim_client import SimClient


async def test_a_sensor_that_cannot_stream_fails_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """The run ends with the sensor's error instead of carrying on with fewer sensors."""

    async def run_client(sim: SimClient, _hello_interval_s: float, stop: asyncio.Event) -> None:
        if sim.name == "front-right":
            raise OSError(98, "Address already in use")
        await stop.wait()

    monkeypatch.setattr(sim_sender, "run_client", run_client)
    argv = [
        "vibesensor-sim",
        "--count=2",
        "--names=front-left,front-right",
        "--duration=60",
        "--speed-kmh=0",
        "--no-road-scene",
        "--no-car-sync",
        "--no-auto-server",
        "--no-interactive",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(OSError, match="Address already in use"):
        await asyncio.wait_for(sim_sender.async_main(sim_sender.parse_args()), 5)
