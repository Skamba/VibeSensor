from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass

import pytest

from vibesensor.ingest.protocol_packing import pack_hello_ack
from vibesensor.ingest.protocol_parsing import parse_hello
from vibesensor.simulator.sim_client import SimClient, make_client_id
from vibesensor.simulator.sim_runtime import command_loop, run_client


@dataclass
class _SummaryFailingClient:
    name: str = "front-left"
    client_id: bytes = b"\x01\x02\x03\x04\x05\x06"
    profile_name: str = "engine_idle"
    scene_mode: str = "road"
    scene_gain: float = 1.0
    scene_noise_gain: float = 1.0
    amp_scale: float = 1.0
    noise_scale: float = 1.0
    paused: bool = False

    @property
    def mac_address(self) -> str:
        return "01:02:03:04:05:06"

    def pulse(self, _strength: float) -> None:
        return None

    def summary(self) -> str:
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_command_loop_handles_command_parse_error_and_continues(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stop_event = asyncio.Event()
    prompts = iter(['bad "quote', "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(prompts))

    await command_loop([], stop_event)

    output = capsys.readouterr().out
    assert stop_event.is_set()
    assert "Command error:" in output
    assert "Stopping simulator..." in output


@pytest.mark.asyncio
async def test_command_loop_propagates_unexpected_command_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop_event = asyncio.Event()
    monkeypatch.setattr("builtins.input", lambda _prompt: "list")

    with pytest.raises(RuntimeError, match="boom"):
        await command_loop([_SummaryFailingClient()], stop_event)


async def test_sensors_on_one_host_each_announce_the_control_port_they_bound() -> None:
    """Each simulated sensor binds its own free control port and the server can reach it.

    A fixed or pre-probed port can be taken by another process before the
    simulator binds it; the sensor then never connected while the run went on.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    server.setblocking(False)
    server_port = server.getsockname()[1]
    sims = [
        SimClient(
            name=f"sim-{index}",
            client_id=make_client_id(index),
            control_port=0,
            sample_rate_hz=800,
            frame_samples=200,
            server_host="127.0.0.1",
            server_data_port=server_port,
            server_control_port=server_port,
            profile_name="rough_road",
        )
        for index in (1, 2)
    ]
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    runs = [asyncio.create_task(run_client(sim, 0.05, stop)) for sim in sims]
    try:
        announced: dict[bytes, int] = {}
        while len(announced) < len(sims):
            data, (_host, source_port) = await asyncio.wait_for(loop.sock_recvfrom(server, 4096), 5)
            hello = parse_hello(data)
            assert hello.control_port == source_port != 0
            announced[hello.client_id] = hello.control_port
        assert len(set(announced.values())) == len(sims)
        for client_id, control_port in announced.items():
            await loop.sock_sendto(server, pack_hello_ack(client_id), ("127.0.0.1", control_port))
        async with asyncio.timeout(5):
            while not all(sim.handshake_complete for sim in sims):
                await asyncio.sleep(0.01)
    finally:
        stop.set()
        await asyncio.gather(*runs, return_exceptions=True)
        server.close()
