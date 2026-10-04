"""The simulator must follow the firmware's handshake, clock-sync, and frame-timing contract."""

from __future__ import annotations

import asyncio
import time
from typing import cast
from unittest.mock import MagicMock

import numpy as np
import pytest

from vibesensor.ingest.protocol_messages import HelloMessage
from vibesensor.ingest.protocol_packing import pack_data, pack_hello, pack_hello_ack
from vibesensor.ingest.protocol_parsing import parse_ack, parse_cmd, parse_data
from vibesensor.ingest.protocol_wire import CMD_SYNC_CLOCK, HELLO_CAP_EXPLICIT_ACK, MSG_HELLO_ACK
from vibesensor.ingest.registry import ClientRegistry, firmware_control_port
from vibesensor.ingest.udp_control_tx import UDPControlPlane
from vibesensor.ingest.udp_data_rx import DataDatagramProtocol
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


def test_a_connecting_sensor_is_on_the_server_clock_right_after_its_hello() -> None:
    """No wait for the periodic broadcast: raw capture drops a sensor's chunks until
    its first frame stamped on the server clock, so each second spent unsynced after
    connecting (or rebooting) mid-run is a second without raw-backed analysis."""
    sim = _make_sim()
    sim_control = _CapturingTransport()
    sim.control_transport = cast(asyncio.DatagramTransport, sim_control)
    sim_protocol = ClientProtocol(sim)
    registry = ClientRegistry()
    server_control = _CapturingTransport()
    plane = UDPControlPlane(registry=registry, bind_host="127.0.0.1", bind_port=9001)
    plane.transport = cast(asyncio.DatagramTransport, server_control)
    plane.protocol.transport = plane.transport
    hello = pack_hello(
        client_id=sim.client_id,
        control_port=sim.control_port,
        sample_rate_hz=sim.sample_rate_hz,
        name=sim.name,
        frame_samples=sim.frame_samples,
        firmware_version="sim",
        capabilities=HELLO_CAP_EXPLICIT_ACK,
    )

    def deliver_until_quiet() -> None:
        to_sim = to_server = 0
        while to_sim < len(server_control.sent) or to_server < len(sim_control.sent):
            for packet, _addr in server_control.sent[to_sim:]:
                sim_protocol.datagram_received(packet, ("127.0.0.1", 9001))
            to_sim = len(server_control.sent)
            for packet, _addr in sim_control.sent[to_server:]:
                plane.protocol.datagram_received(packet, ("127.0.0.1", sim.control_port))
            to_server = len(sim_control.sent)

    plane.protocol.datagram_received(hello, ("127.0.0.1", sim.control_port))
    deliver_until_quiet()

    record = registry.get(sim.client_id.hex())
    assert record is not None
    assert sim.handshake_complete is True
    assert record.clock_offset_applied is True
    server_now_us = int(time.monotonic() * 1_000_000)
    assert abs((sim.device_time_us() + sim.clock_offset_us) - server_now_us) < 5_000
    # HELLO_ACK, then the measuring and the applying exchange.
    assert len(server_control.sent) == 3

    # A synced sensor's periodic HELLO gets only its HELLO_ACK.
    plane.protocol.datagram_received(hello, ("127.0.0.1", sim.control_port))
    assert len(server_control.sent) == 4
    assert server_control.sent[-1][0][0] == MSG_HELLO_ACK


def test_a_sensor_streaming_before_its_hello_is_synced_from_its_data() -> None:
    """After a server restart a sensor keeps streaming (its handshake is done) and
    says HELLO only every 2 s. Waiting for that HELLO cost a recording started at
    once ~1.6 s of raw capture; its DATA now starts the exchanges, one at a time."""
    sim = _make_sim()
    # Like the firmware, the sensor listens on its MAC-derived control port.
    sim.control_port = firmware_control_port(sim.client_id.hex())
    sim.handshake_complete = True
    sim.clock_offset_us = 7_000_000  # the offset the restarted server had applied
    sim_control = _CapturingTransport()
    sim.control_transport = cast(asyncio.DatagramTransport, sim_control)
    sim_protocol = ClientProtocol(sim)
    registry = ClientRegistry()
    server_control = _CapturingTransport()
    plane = UDPControlPlane(registry=registry, bind_host="127.0.0.1", bind_port=9001)
    plane.transport = cast(asyncio.DatagramTransport, server_control)
    processor = MagicMock()
    data_protocol = DataDatagramProtocol(
        registry=registry, processor=processor, sync_clock_now=plane.send_sync_clock
    )
    data_addr = ("127.0.0.1", 50123)  # the data socket's ephemeral port
    seq = iter(range(1_000))

    def stream_frames(count: int) -> None:
        for _ in range(count):
            t0_us = sim.device_time_us() + sim.clock_offset_us
            samples = np.zeros((sim.frame_samples, 3), dtype=np.int16)
            packet = pack_data(sim.client_id, next(seq), t0_us, samples)
            data_protocol._process_datagram(packet, data_addr)

    def deliver_control(packets: list[tuple[bytes, tuple[str, int]]], start: int) -> None:
        for packet, addr in packets[start:]:
            assert addr == ("127.0.0.1", sim.control_port)
            sim_protocol.datagram_received(packet, ("127.0.0.1", 9001))

    measure_start_s = time.monotonic()
    stream_frames(5)
    # Five frames before the sensor answers start one measuring exchange, not five.
    assert [parse_cmd(packet).cmd_id for packet, _addr in server_control.sent] == [CMD_SYNC_CLOCK]
    deliver_control(server_control.sent, 0)
    plane.protocol.datagram_received(sim_control.sent[-1][0], ("127.0.0.1", sim.control_port))
    # The measured offset is off by at most half the exchange's round trip, which
    # here includes the frames streamed while it was in flight.
    max_offset_error_us = int((time.monotonic() - measure_start_s) * 500_000) + 1_000
    # The measured offset goes out at once in the applying exchange.
    assert len(server_control.sent) == 2
    stream_frames(3)
    assert len(server_control.sent) == 2
    deliver_control(server_control.sent, 1)
    plane.protocol.datagram_received(sim_control.sent[-1][0], ("127.0.0.1", sim.control_port))

    record = registry.get(sim.client_id.hex())
    assert record is not None
    assert record.clock_offset_applied is True
    server_now_us = int(time.monotonic() * 1_000_000)
    assert abs((sim.device_time_us() + sim.clock_offset_us) - server_now_us) <= max_offset_error_us
    stream_frames(1)
    assert len(server_control.sent) == 2
    # The next frame is on the server clock, so it reaches the live buffer stamped
    # (and raw capture) without any HELLO from the sensor.
    assert processor.ingest.call_args.kwargs["t0_us"] is not None


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
