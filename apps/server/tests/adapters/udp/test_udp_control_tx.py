"""UDP control-plane coverage for ACK handling, HELLO_ACK behavior, and shutdown."""

from __future__ import annotations

import logging
import struct
from pathlib import Path

import pytest

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.adapters.udp.protocol import (
    HELLO_CAP_EXPLICIT_ACK,
    MSG_HELLO_ACK,
    HelloMessage,
    pack_ack,
    pack_ack_sync_clock,
    pack_hello,
    parse_cmd,
)
from vibesensor.adapters.udp.udp_control_tx import ControlDatagramProtocol, UDPControlPlane
from vibesensor.infra.runtime.registry import ClientRegistry


def _make_registry(tmp_path: Path) -> ClientRegistry:
    adapters = create_history_persistence_adapters(tmp_path / "history.db")
    return ClientRegistry(db=adapters.client_name_repository)


@pytest.mark.parametrize(
    "client_id_input",
    [
        "aabbccddeeff",
        "aa:bb:cc:dd:ee:ff",
    ],
)
def test_send_identify_accepts_hex_and_mac_client_ids(
    tmp_path: Path,
    client_id_input: str,
    fake_transport,
) -> None:
    client_hex = "aabbccddeeff"
    registry = _make_registry(tmp_path)
    registry.update_from_hello(
        HelloMessage(
            client_id=bytes.fromhex(client_hex),
            control_port=9010,
            sample_rate_hz=800,
            name="node",
            firmware_version="fw",
        ),
        ("127.0.0.1", 54000),
        now=1.0,
    )

    plane = UDPControlPlane(registry=registry, bind_host="127.0.0.1", bind_port=9001)
    plane.transport = fake_transport

    ok, cmd_seq = plane.send_identify(client_id_input, 1500)

    assert ok is True
    assert isinstance(cmd_seq, int)
    assert fake_transport.sent
    payload, addr = fake_transport.sent[0]
    assert addr == ("127.0.0.1", 9010)

    cmd = parse_cmd(payload)
    assert cmd.client_id.hex() == client_hex


def test_control_datagram_programming_bug_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_hex = "aabbccddeeff"
    registry = _make_registry(tmp_path)
    protocol = ControlDatagramProtocol(registry)
    packet = pack_ack(bytes.fromhex(client_hex), cmd_seq=7, status=0)

    def boom(_: bytes) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr("vibesensor.adapters.udp.udp_control_tx.parse_ack", boom)

    with pytest.raises(RuntimeError, match="boom"):
        protocol.datagram_received(packet, ("127.0.0.1", 9001))

    assert registry.get(client_hex) is None


def test_control_datagram_operational_error_is_logged_and_counted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client_hex = "aabbccddeeff"
    registry = _make_registry(tmp_path)
    registry.update_from_hello(
        HelloMessage(
            client_id=bytes.fromhex(client_hex),
            control_port=9010,
            sample_rate_hz=800,
            name="node",
            firmware_version="fw",
        ),
        ("127.0.0.1", 54000),
        now=1.0,
    )
    protocol = ControlDatagramProtocol(registry)
    packet = pack_ack(bytes.fromhex(client_hex), cmd_seq=7, status=0)

    def raise_oserror(_ack: object, _now_ts: float, *, now_mono: float | None = None) -> None:
        raise OSError("socket boom")

    monkeypatch.setattr(registry, "update_from_ack", raise_oserror)

    with caplog.at_level(logging.WARNING):
        protocol.datagram_received(packet, ("127.0.0.1", 9001))

    record = registry.get(client_hex)
    assert record is not None
    assert record.parse_errors == 1
    assert "Unexpected error processing control datagram" in caplog.text


def test_control_datagram_sends_hello_ack_for_capable_firmware(
    tmp_path: Path,
    fake_transport,
) -> None:
    registry = _make_registry(tmp_path)
    protocol = ControlDatagramProtocol(registry)
    protocol.transport = fake_transport
    packet = pack_hello(
        client_id=bytes.fromhex("aabbccddeeff"),
        control_port=9010,
        sample_rate_hz=800,
        name="node",
        frame_samples=200,
        firmware_version="fw",
        capabilities=HELLO_CAP_EXPLICIT_ACK,
    )

    protocol.datagram_received(packet, ("127.0.0.1", 54000))

    assert len(fake_transport.sent) == 1
    payload, addr = fake_transport.sent[0]
    assert payload[0] == MSG_HELLO_ACK
    assert addr == ("127.0.0.1", 9010)


def test_close_closes_transport_once_and_clears_reference(tmp_path: Path, fake_transport) -> None:
    registry = _make_registry(tmp_path)
    plane = UDPControlPlane(registry=registry, bind_host="127.0.0.1", bind_port=9001)
    plane.transport = fake_transport

    plane.close()

    assert fake_transport.closed is True
    assert plane.transport is None


def test_broadcast_sync_clock_rolls_ack_timestamps_into_next_sync_payload(
    tmp_path: Path,
    fake_transport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_hex = "aabbccddeeff"
    registry = _make_registry(tmp_path)
    registry.update_from_hello(
        HelloMessage(
            client_id=bytes.fromhex(client_hex),
            control_port=9010,
            sample_rate_hz=800,
            name="node",
            firmware_version="fw",
        ),
        ("127.0.0.1", 54000),
        now=1.0,
    )
    plane = UDPControlPlane(registry=registry, bind_host="127.0.0.1", bind_port=9001)
    plane.transport = fake_transport

    current_mono = [1.0]
    monkeypatch.setattr(
        "vibesensor.adapters.udp.udp_control_tx.time.monotonic",
        lambda: current_mono[0],
    )
    monkeypatch.setattr("vibesensor.adapters.udp.udp_control_tx.time.time", lambda: 1000.0)

    assert plane.broadcast_sync_clock() == 1
    first_payload, _addr = fake_transport.sent[-1]
    first_cmd = parse_cmd(first_payload)
    first_server_time_us, first_offset_us, first_round_trip_us = struct.unpack(
        "<QqI", first_cmd.params
    )
    assert (first_server_time_us, first_offset_us, first_round_trip_us) == (1_000_000, 0, 0)

    current_mono[0] = 1.0045
    ack_packet = pack_ack_sync_clock(
        bytes.fromhex(client_hex),
        cmd_seq=first_cmd.cmd_seq,
        device_receive_us=997_000,
        device_send_us=997_500,
    )
    plane.protocol.datagram_received(ack_packet, ("127.0.0.1", 9010))

    record = registry.get(client_hex)
    assert record is not None
    assert record.sync_offset_us == 5_000
    assert record.sync_rtt_us == 4_000

    current_mono[0] = 2.0
    assert plane.broadcast_sync_clock() == 1
    second_payload, _addr = fake_transport.sent[-1]
    second_cmd = parse_cmd(second_payload)
    second_server_time_us, second_offset_us, second_round_trip_us = struct.unpack(
        "<QqI", second_cmd.params
    )
    assert (second_server_time_us, second_offset_us, second_round_trip_us) == (
        2_000_000,
        5_000,
        4_000,
    )

    plane.close()

    assert fake_transport.closed is True
    assert plane.transport is None
