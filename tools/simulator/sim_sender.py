from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path
import random
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pi"))

from vibesenser.protocol import (  # noqa: E402
    CMD_IDENTIFY,
    MSG_CMD,
    pack_ack,
    pack_data,
    pack_hello,
    parse_cmd,
)


@dataclass(slots=True)
class SimClient:
    name: str
    client_id: bytes
    control_port: int
    sample_rate_hz: int
    frame_samples: int
    server_host: str
    server_data_port: int
    server_control_port: int
    seq: int = 0
    phase: float = 0.0
    transport: asyncio.DatagramTransport | None = None

    def make_frame(self) -> np.ndarray:
        dt = 1.0 / self.sample_rate_hz
        t = self.phase + np.arange(self.frame_samples, dtype=np.float32) * dt
        base = int(self.client_id[-1]) % 9
        x = 550 * np.sin(2 * np.pi * (11 + base) * t)
        y = 320 * np.sin(2 * np.pi * (22 + base) * t + 0.5)
        z = 800 * np.sin(2 * np.pi * (35 + base) * t + 1.2)
        noise = np.random.normal(0.0, 25.0, size=(self.frame_samples, 3))
        frame = np.stack([x, y, z], axis=1) + noise
        self.phase = float(t[-1] + dt)
        return frame.astype(np.int16)


class ClientProtocol(asyncio.DatagramProtocol):
    def __init__(self, sim: SimClient):
        self.sim = sim

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.sim.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if not data or data[0] != MSG_CMD:
            return
        try:
            cmd = parse_cmd(data)
        except Exception:
            return
        if cmd.client_id != self.sim.client_id:
            return
        if cmd.cmd_id == CMD_IDENTIFY:
            duration_ms = int.from_bytes(cmd.params[:2], "little") if len(cmd.params) >= 2 else 1000
            print(f"{self.sim.name}: identify for {duration_ms}ms from {addr[0]}:{addr[1]}")
            ack = pack_ack(self.sim.client_id, cmd.cmd_seq, status=0)
            if self.sim.transport is not None:
                self.sim.transport.sendto(ack, (self.sim.server_host, self.sim.server_control_port))


async def run_client(sim: SimClient, hello_interval_s: float) -> None:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: ClientProtocol(sim),
        local_addr=("0.0.0.0", sim.control_port),
    )
    sim.transport = transport
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(hello_loop(sim, hello_interval_s))
            tg.create_task(data_loop(sim))
    finally:
        transport.close()


async def hello_loop(sim: SimClient, hello_interval_s: float) -> None:
    while True:
        if sim.transport is not None:
            packet = pack_hello(
                client_id=sim.client_id,
                control_port=sim.control_port,
                sample_rate_hz=sim.sample_rate_hz,
                name=sim.name,
                firmware_version="sim-0.1",
            )
            sim.transport.sendto(packet, (sim.server_host, sim.server_control_port))
        await asyncio.sleep(hello_interval_s)


async def data_loop(sim: SimClient) -> None:
    frame_period = sim.frame_samples / sim.sample_rate_hz
    next_send = asyncio.get_running_loop().time()
    while True:
        if sim.transport is not None:
            samples = sim.make_frame()
            packet = pack_data(
                client_id=sim.client_id,
                seq=sim.seq,
                t0_us=time.monotonic_ns() // 1000,
                samples=samples,
            )
            sim.transport.sendto(packet, (sim.server_host, sim.server_data_port))
            sim.seq = (sim.seq + 1) & 0xFFFFFFFF
        next_send += frame_period
        await asyncio.sleep(max(0.0, next_send - asyncio.get_running_loop().time()))


def make_client_id(seed: int) -> bytes:
    rng = random.Random(seed)
    return bytes([0xD0, 0x5A, rng.randrange(0, 255), rng.randrange(0, 255), rng.randrange(0, 255), seed & 0xFF])


async def async_main(args: argparse.Namespace) -> None:
    names = [n.strip() for n in args.names.split(",") if n.strip()] if args.names else []
    while len(names) < args.count:
        names.append(f"sim-{len(names) + 1}")

    clients = [
        SimClient(
            name=names[i],
            client_id=make_client_id(i + 1),
            control_port=args.client_control_base + i,
            sample_rate_hz=args.sample_rate_hz,
            frame_samples=args.frame_samples,
            server_host=args.server_host,
            server_data_port=args.server_data_port,
            server_control_port=args.server_control_port,
        )
        for i in range(args.count)
    ]

    print(f"Starting {len(clients)} simulated clients -> {args.server_host}:{args.server_data_port}")
    async with asyncio.TaskGroup() as tg:
        for client in clients:
            tg.create_task(run_client(client, args.hello_interval))
        if args.duration > 0:
            await asyncio.sleep(args.duration)
            raise asyncio.CancelledError()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VibeSenser UDP simulator")
    parser.add_argument("--server-host", default="127.0.0.1")
    parser.add_argument("--server-data-port", type=int, default=9000)
    parser.add_argument("--server-control-port", type=int, default=9001)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--names", default="front-left,front-right,rear")
    parser.add_argument("--sample-rate-hz", type=int, default=800)
    parser.add_argument("--frame-samples", type=int, default=200)
    parser.add_argument("--hello-interval", type=float, default=2.0)
    parser.add_argument("--client-control-base", type=int, default=9100)
    parser.add_argument("--duration", type=float, default=0.0, help="Optional run duration in seconds")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        pass
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    main()

