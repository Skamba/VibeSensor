"""The simulator must follow the firmware's handshake, clock-sync, and frame-timing contract."""

from __future__ import annotations

import asyncio
import time
from typing import cast

import pytest

from vibesensor.ingest.protocol import (
    HelloMessage,
    pack_hello_ack,
    parse_ack,
    parse_data,
)
from vibesensor.ingest.registry import ClientRegistry
from vibesensor.ingest.udp_control_tx import UDPControlPlane
from vibesensor.simulator.sim_client import SimClient, make_client_id
from vibesensor.simulator.sim_runtime import ClientProtocol, data_loop


class _CapturingTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((bytes(data), addr))


def _make_sim(*, frame_samples: int = 200) -> SimClient:
    return SimClient(
        name="front-left",
        client_id=make_client_id(1),
        control_port=9101,
        sample_rate_hz=800,
        frame_samples=frame_samples,
        server_host="127.0.0.1",
        server_data_port=9000,
        server_control_port=9001,
        profile_name="rough_road",
    )


def test_sim_clock_sync_rounds_put_t0_in_the_server_clock_domain() -> None:
    sim = _make_sim()
    sim_control = _CapturingTransport()
    sim.control_transport = cast(asyncio.DatagramTransport, sim_control)
    sim_protocol = ClientProtocol(sim)

    registry = ClientRegistry()
    registry.update_from_hello(
        HelloMessage(
            client_id=sim.client_id,
            control_port=sim.control_port,
            sample_rate_hz=sim.sample_rate_hz,
            name=sim.name,
            frame_samples=sim.frame_samples,
            firmware_version="sim",
        ),
        ("127.0.0.1", sim.control_port),
    )
    server_control = _CapturingTransport()
    plane = UDPControlPlane(registry=registry, bind_host="127.0.0.1", bind_port=9001)
    plane.transport = cast(asyncio.DatagramTransport, server_control)

    # The device timer counts from the simulated boot, not the server clock.
    assert abs(sim.device_time_us() - int(time.monotonic() * 1_000_000)) > 500_000

    for round_index in range(2):
        assert plane.broadcast_sync_clock() == 1
        cmd_packet, _addr = server_control.sent[-1]
        sim_protocol.datagram_received(cmd_packet, ("127.0.0.1", 9001))
        ack_packet, ack_addr = sim_control.sent[-1]
        assert ack_addr == ("127.0.0.1", sim.server_control_port)
        ack = parse_ack(ack_packet)
        assert ack.device_receive_us is not None
        assert ack.device_send_us is not None
        plane.protocol.datagram_received(ack_packet, ("127.0.0.1", sim.control_port))
        if round_index == 0:
            # Like the firmware, the first exchange carries no RTT, so no offset is applied.
            assert sim.clock_offset_us == 0

    record = registry.get(sim.client_id.hex())
    assert record is not None
    assert record.sync_rtt_us is not None
    assert record.sync_rtt_us < 50_000
    assert record.last_sync_monotonic_us is not None
    assert sim.clock_offset_us != 0
    server_now_us = int(time.monotonic() * 1_000_000)
    assert abs((sim.device_time_us() + sim.clock_offset_us) - server_now_us) < 5_000


def test_sim_marks_handshake_complete_only_for_its_own_hello_ack() -> None:
    sim = _make_sim()
    protocol = ClientProtocol(sim)

    protocol.datagram_received(pack_hello_ack(make_client_id(2)), ("127.0.0.1", 9001))
    assert sim.handshake_complete is False

    protocol.datagram_received(pack_hello_ack(sim.client_id), ("127.0.0.1", 9001))
    assert sim.handshake_complete is True


@pytest.mark.asyncio
async def test_data_loop_sends_nothing_before_hello_ack() -> None:
    sim = _make_sim()
    data = _CapturingTransport()
    sim.data_transport = cast(asyncio.DatagramTransport, data)
    stop_event = asyncio.Event()

    task = asyncio.create_task(data_loop(sim, stop_event))
    await asyncio.sleep(0.15)
    stop_event.set()
    await task

    assert data.sent == []


@pytest.mark.asyncio
async def test_data_loop_t0_follows_the_sample_clock_not_transmit_jitter() -> None:
    sim = _make_sim(frame_samples=40)
    sim.handshake_complete = True
    sim.send_jitter_s = 0.02
    sim.clock_offset_us = 123_456_789
    data = _CapturingTransport()
    sim.data_transport = cast(asyncio.DatagramTransport, data)
    stop_event = asyncio.Event()

    task = asyncio.create_task(data_loop(sim, stop_event))
    await asyncio.sleep(0.4)
    stop_event.set()
    await task

    frames = [parse_data(packet) for packet, _addr in data.sent]
    assert len(frames) >= 3
    assert [frame.seq for frame in frames] == list(range(len(frames)))
    frame_duration_us = 40 * 1_000_000 // 800
    deltas = {b.t0_us - a.t0_us for a, b in zip(frames, frames[1:], strict=False)}
    assert deltas == {frame_duration_us}
    first_device_t0_us = frames[0].t0_us - sim.clock_offset_us
    assert 0 < first_device_t0_us < sim.device_time_us()
