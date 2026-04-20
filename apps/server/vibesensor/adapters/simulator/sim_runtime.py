from __future__ import annotations

import asyncio
import time
from typing import cast

from vibesensor.adapters.simulator.commands import apply_command
from vibesensor.adapters.simulator.profiles import PROFILE_LIBRARY
from vibesensor.adapters.simulator.sim_client import SimClient
from vibesensor.adapters.simulator.sim_scene import RoadSceneController
from vibesensor.adapters.udp.protocol import (
    CMD_IDENTIFY,
    HELLO_CAP_EXPLICIT_ACK,
    MSG_CMD,
    pack_ack,
    pack_data,
    pack_hello,
    parse_cmd,
)
from vibesensor.shared.exceptions import ProtocolError

__all__ = [
    "ClientProtocol",
    "DataProtocol",
    "auto_stop",
    "command_loop",
    "data_loop",
    "hello_loop",
    "road_scene_loop",
    "run_client",
    "wait_stop",
]


class ClientProtocol(asyncio.DatagramProtocol):
    def __init__(self, sim: SimClient):
        self.sim = sim

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.sim.control_transport = cast(asyncio.DatagramTransport, transport)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if not data or data[0] != MSG_CMD:
            return
        try:
            cmd = parse_cmd(data)
        except (ProtocolError, ValueError) as exc:
            print(f"{self.sim.name}: ignoring unparseable command from {addr[0]}:{addr[1]}: {exc}")
            return
        if cmd.client_id != self.sim.client_id:
            return
        if cmd.cmd_id == CMD_IDENTIFY:
            duration_ms = int.from_bytes(cmd.params[:2], "little") if len(cmd.params) >= 2 else 1000
            print(f"{self.sim.name}: identify {duration_ms}ms from {addr[0]}:{addr[1]}")
            self.sim.pulse(1.4)
            ack = pack_ack(self.sim.client_id, cmd.cmd_seq, status=0)
            if self.sim.control_transport is not None:
                self.sim.control_transport.sendto(
                    ack, (self.sim.server_host, self.sim.server_control_port)
                )


class DataProtocol(asyncio.DatagramProtocol):
    def __init__(self, sim: SimClient):
        self.sim = sim

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.sim.data_transport = cast(asyncio.DatagramTransport, transport)


async def command_loop(clients: list[SimClient], stop_event: asyncio.Event) -> None:
    print("Interactive mode enabled. Type 'help' for commands.")
    while not stop_event.is_set():
        try:
            line = await asyncio.to_thread(input, "sim> ")
        except (EOFError, KeyboardInterrupt):
            stop_event.set()
            break
        try:
            out = apply_command(clients, line, stop_event, list(PROFILE_LIBRARY.keys()))
        except ValueError as exc:
            print(f"Command error: {exc}")
            continue
        if out:
            print(out)


async def road_scene_loop(clients: list[SimClient], stop_event: asyncio.Event) -> None:
    if not clients:
        return
    controller = RoadSceneController(clients)
    while not stop_event.is_set():
        mode, duration = controller.next_scene()
        print(f"[road-scene] mode={mode} duration={duration:.1f}s")
        await asyncio.sleep(duration)


async def run_client(sim: SimClient, hello_interval_s: float, stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    control_transport, _ = await loop.create_datagram_endpoint(
        lambda: ClientProtocol(sim),
        local_addr=("0.0.0.0", sim.control_port),
    )
    data_transport, _ = await loop.create_datagram_endpoint(
        lambda: DataProtocol(sim),
        local_addr=("0.0.0.0", 0),
    )
    sim.control_transport = control_transport
    sim.data_transport = data_transport
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(hello_loop(sim, hello_interval_s, stop_event))
            tg.create_task(data_loop(sim, stop_event))
            tg.create_task(wait_stop(stop_event))
    finally:
        control_transport.close()
        data_transport.close()


async def wait_stop(stop_event: asyncio.Event) -> None:
    await stop_event.wait()
    raise asyncio.CancelledError()


async def hello_loop(sim: SimClient, hello_interval_s: float, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        if sim.control_transport is not None:
            packet = pack_hello(
                client_id=sim.client_id,
                control_port=sim.control_port,
                sample_rate_hz=sim.sample_rate_hz,
                name=sim.name,
                frame_samples=sim.frame_samples,
                firmware_version="sim-0.2",
                capabilities=HELLO_CAP_EXPLICIT_ACK,
            )
            sim.control_transport.sendto(packet, (sim.server_host, sim.server_control_port))
        await asyncio.sleep(hello_interval_s)


async def data_loop(sim: SimClient, stop_event: asyncio.Event) -> None:
    if sim.rng is None:
        raise RuntimeError("SimClient.rng must be initialised before data_loop")
    frame_period = (sim.frame_samples / sim.sample_rate_hz) * sim.send_period_scale
    loop = asyncio.get_running_loop()
    next_send = loop.time() + sim.start_offset_s
    while not stop_event.is_set():
        if sim.data_transport is not None:
            samples = sim.make_frame()
            packet = pack_data(
                client_id=sim.client_id,
                seq=sim.seq,
                t0_us=time.monotonic_ns() // 1000,
                samples=samples,
            )
            sim.data_transport.sendto(packet, (sim.server_host, sim.server_data_port))
            sim.seq = (sim.seq + 1) & 0xFFFFFFFF
        next_send += frame_period
        jitter = float(sim.rng.uniform(-sim.send_jitter_s, sim.send_jitter_s))
        await asyncio.sleep(max(0.0, (next_send + jitter) - loop.time()))


async def auto_stop(delay_s: float, stop_event: asyncio.Event) -> None:
    await asyncio.sleep(delay_s)
    stop_event.set()
