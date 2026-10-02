from __future__ import annotations

import asyncio
import contextlib
import time
from typing import cast
from urllib.error import URLError

from vibesensor.common.exceptions import ProtocolError
from vibesensor.ingest.protocol_packing import pack_ack, pack_ack_sync_clock, pack_data, pack_hello
from vibesensor.ingest.protocol_parsing import parse_cmd, parse_hello_ack
from vibesensor.ingest.protocol_wire import (
    CMD_IDENTIFY,
    CMD_SYNC_CLOCK,
    CMD_SYNC_CLOCK_STRUCT,
    HELLO_CAP_EXPLICIT_ACK,
    MSG_CMD,
    MSG_HELLO_ACK,
)
from vibesensor.simulator.commands import apply_command
from vibesensor.simulator.profiles import DEFAULT_SPEED_KMH, PROFILE_LIBRARY
from vibesensor.simulator.server_http import fetch_active_car_order_hz
from vibesensor.simulator.sim_client import SimClient
from vibesensor.simulator.sim_scene import RoadSceneController

_HANDSHAKE_POLL_S = 0.05
_ACTIVE_CAR_POLL_S = 2.0

__all__ = [
    "ClientProtocol",
    "DataProtocol",
    "active_car_order_loop",
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
        if not data:
            return
        if data[0] == MSG_HELLO_ACK:
            self._handle_hello_ack(data)
            return
        if data[0] != MSG_CMD:
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
            self._send_control(pack_ack(self.sim.client_id, cmd.cmd_seq, status=0))
        elif cmd.cmd_id == CMD_SYNC_CLOCK:
            self._handle_sync_clock(data, cmd.cmd_seq)

    def _send_control(self, packet: bytes) -> None:
        if self.sim.control_transport is not None:
            self.sim.control_transport.sendto(
                packet, (self.sim.server_host, self.sim.server_control_port)
            )

    def _handle_hello_ack(self, data: bytes) -> None:
        try:
            hello_ack = parse_hello_ack(data)
        except (ProtocolError, ValueError):
            return
        if hello_ack.client_id == self.sim.client_id:
            self.sim.handshake_complete = True

    def _handle_sync_clock(self, data: bytes, cmd_seq: int) -> None:
        """Mirror the firmware's CMD_SYNC_CLOCK handling (runtime_transport.cpp).

        The server's offset estimate (from the previous exchange) is applied
        once it carries a measured round trip, and the ACK reports device
        receive/send timestamps so the server can refresh its estimate.
        """
        if len(data) < CMD_SYNC_CLOCK_STRUCT.size:
            return
        device_receive_us = self.sim.device_time_us()
        *_header, _server_time_us, applied_offset_us, round_trip_us = (
            CMD_SYNC_CLOCK_STRUCT.unpack_from(data, 0)
        )
        if round_trip_us > 0:
            self.sim.clock_offset_us = int(applied_offset_us)
        device_send_us = self.sim.device_time_us()
        self._send_control(
            pack_ack_sync_clock(
                self.sim.client_id,
                cmd_seq,
                device_receive_us=device_receive_us,
                device_send_us=device_send_us,
            )
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
    """Stream DATA frames the way the ESP firmware does.

    Like the firmware, streaming starts only after the server's HELLO_ACK.
    Samples are scheduled on the simulated device timer, so consecutive frames
    are exactly ``frame_samples / sample_rate_hz`` apart in ``t0_us`` (device
    time plus the synced clock offset), independent of transmit jitter.
    """
    if sim.rng is None:
        raise RuntimeError("SimClient.rng must be initialised before data_loop")
    while not sim.handshake_complete:
        if stop_event.is_set():
            return
        await asyncio.sleep(_HANDSHAKE_POLL_S)
    frame_duration_us = (sim.frame_samples * 1_000_000.0) / sim.sample_rate_hz
    first_due_us = float(sim.device_time_us()) + (sim.start_offset_s * 1_000_000.0)
    frame_index = 0
    while not stop_event.is_set():
        frame_start_us = first_due_us + (frame_index * frame_duration_us)
        # A frame is ready once its last sample has been taken (device time).
        ready_mono_s = sim.monotonic_at_device_us(frame_start_us + frame_duration_us)
        tx_delay_s = float(sim.rng.uniform(0.0, sim.send_jitter_s))
        await asyncio.sleep(max(0.0, (ready_mono_s + tx_delay_s) - time.monotonic()))
        if stop_event.is_set():
            break
        samples = sim.make_frame()
        if sim.data_transport is not None:
            packet = pack_data(
                client_id=sim.client_id,
                seq=sim.seq,
                t0_us=max(0, int(round(frame_start_us)) + sim.clock_offset_us),
                samples=samples,
            )
            sim.data_transport.sendto(packet, (sim.server_host, sim.server_data_port))
        sim.seq = (sim.seq + 1) & 0xFFFFFFFF
        frame_index += 1


async def active_car_order_loop(
    clients: list[SimClient],
    stop_event: asyncio.Event,
    *,
    server_host: str,
    server_http_port: int,
    server_check_timeout: float,
    poll_interval_s: float = _ACTIVE_CAR_POLL_S,
) -> None:
    """Keep order-locked tones on the server's active car (tire size, ratios).

    Real sensors see the car's actual wheel/driveline orders; without this the
    simulator would inject orders for the default car profile, several percent
    away from whatever car the server analyzes against.
    """
    applied: dict[str, float] | None = None
    while not stop_event.is_set():
        try:
            order_hz = await asyncio.to_thread(
                fetch_active_car_order_hz,
                server_host,
                server_http_port,
                server_check_timeout,
            )
        except (URLError, OSError, TimeoutError, ValueError):
            order_hz = None
        if order_hz is not None and order_hz != applied:
            for client in clients:
                client.order_hz = dict(order_hz)
            applied = order_hz
            print(
                "[car] order tones follow the active car: "
                f"wheel1={order_hz['wheel_1x']:.3f}Hz shaft1={order_hz['shaft_1x']:.3f}Hz "
                f"engine1={order_hz['engine_1x']:.3f}Hz at {DEFAULT_SPEED_KMH:.0f} km/h"
            )
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_s)


async def auto_stop(delay_s: float, stop_event: asyncio.Event) -> None:
    await asyncio.sleep(delay_s)
    stop_event.set()
