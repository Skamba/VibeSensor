"""UDP protocol round-trip and payload memory contracts."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from vibesensor.adapters.udp.protocol import (
    CMD_IDENTIFY,
    CMD_SYNC_CLOCK,
    HELLO_CAP_EXPLICIT_ACK,
    MSG_DATA,
    MSG_DATA_ACK,
    MSG_HELLO,
    MSG_HELLO_ACK,
    client_id_mac,
    pack_ack,
    pack_ack_sync_clock,
    pack_cmd_identify,
    pack_cmd_sync_clock,
    pack_data,
    pack_data_ack,
    pack_hello,
    pack_hello_ack,
    parse_ack,
    parse_client_id,
    parse_cmd,
    parse_data,
    parse_data_ack,
    parse_hello,
    parse_hello_ack,
)


def test_hello_roundtrip() -> None:
    client_id = bytes.fromhex("a1b2c3d4e5f6")
    pkt = pack_hello(
        client_id=client_id,
        control_port=9123,
        sample_rate_hz=800,
        name="front-left",
        frame_samples=200,
        firmware_version="fw-test",
        queue_overflow_drops=7,
        capabilities=HELLO_CAP_EXPLICIT_ACK,
    )

    assert pkt[0] == MSG_HELLO
    decoded = parse_hello(pkt)
    assert decoded.client_id == client_id
    assert decoded.control_port == 9123
    assert decoded.sample_rate_hz == 800
    assert decoded.frame_samples == 200
    assert decoded.name == "front-left"
    assert decoded.firmware_version == "fw-test"
    assert decoded.queue_overflow_drops == 7
    assert decoded.capabilities == HELLO_CAP_EXPLICIT_ACK


def test_data_roundtrip() -> None:
    client_id = bytes.fromhex("010203040506")
    samples = np.array([[1, 2, 3], [4, 5, 6], [-2, -1, 0]], dtype=np.int16)

    pkt = pack_data(client_id=client_id, seq=17, t0_us=123_456_789, samples=samples)

    assert pkt[0] == MSG_DATA
    decoded = parse_data(pkt)
    assert decoded.client_id == client_id
    assert decoded.seq == 17
    assert decoded.t0_us == 123_456_789
    np.testing.assert_array_equal(decoded.samples, samples)


def test_parse_data_returns_read_only_view_over_datagram_payload() -> None:
    client_id = bytes.fromhex("010203040506")
    samples = np.array([[1, 2, 3], [4, 5, 6], [-2, -1, 0]], dtype=np.int16)
    pkt = pack_data(client_id=client_id, seq=17, t0_us=123_456_789, samples=samples)

    decoded = parse_data(pkt)

    assert decoded.samples.flags.owndata is False
    assert decoded.samples.flags.writeable is False
    assert np.shares_memory(decoded.samples, np.frombuffer(pkt, dtype=np.uint8))
    with pytest.raises(ValueError, match="read-only"):
        decoded.samples[0, 0] = 99


def test_parse_identify_cmd() -> None:
    client_id = bytes.fromhex("112233445566")
    cmd = pack_cmd_identify(client_id, cmd_seq=42, duration_ms=1500)

    parsed = parse_cmd(cmd)

    assert parsed.client_id == client_id
    assert parsed.cmd_id == CMD_IDENTIFY
    assert parsed.cmd_seq == 42
    assert int.from_bytes(parsed.params[:2], "little") == 1500


def test_pack_cmd_identify_clamps_duration_bounds() -> None:
    client_id = bytes.fromhex("112233445566")

    low = parse_cmd(pack_cmd_identify(client_id, cmd_seq=1, duration_ms=0))
    high = parse_cmd(pack_cmd_identify(client_id, cmd_seq=2, duration_ms=999999))

    assert int.from_bytes(low.params[:2], "little") == 1
    assert int.from_bytes(high.params[:2], "little") == 60_000


def test_pack_cmd_sync_clock_clamps_negative_server_time() -> None:
    client_id = bytes.fromhex("112233445566")
    parsed = parse_cmd(
        pack_cmd_sync_clock(
            client_id,
            cmd_seq=7,
            server_time_us=-123,
            applied_offset_us=-456,
            round_trip_us=-789,
        )
    )

    assert parsed.cmd_id == CMD_SYNC_CLOCK
    assert parsed.cmd_seq == 7
    server_time_us, applied_offset_us, round_trip_us = struct.unpack("<QqI", parsed.params)
    assert server_time_us == 0
    assert applied_offset_us == -456
    assert round_trip_us == 0


def test_pack_cmd_sync_clock_roundtrip_includes_offset_and_rtt() -> None:
    client_id = bytes.fromhex("112233445566")

    parsed = parse_cmd(
        pack_cmd_sync_clock(
            client_id,
            cmd_seq=9,
            server_time_us=123_456_789,
            applied_offset_us=-3_210,
            round_trip_us=4_567,
        )
    )

    assert parsed.cmd_id == CMD_SYNC_CLOCK
    assert parsed.cmd_seq == 9
    assert struct.unpack("<QqI", parsed.params) == (123_456_789, -3_210, 4_567)


def test_pack_hello_truncates_name_and_firmware_to_32_bytes() -> None:
    client_id = bytes.fromhex("010203040506")

    decoded = parse_hello(pack_hello(client_id, 9000, 800, "n" * 64, firmware_version="f" * 64))

    assert decoded.name == "n" * 32
    assert decoded.firmware_version == "f" * 32


def test_ack_roundtrip() -> None:
    client_id = bytes.fromhex("aabbccddeeff")
    pkt = pack_ack(client_id, cmd_seq=99, status=0)

    decoded = parse_ack(pkt)

    assert decoded.client_id == client_id
    assert decoded.cmd_seq == 99
    assert decoded.status == 0
    assert decoded.device_receive_us is None
    assert decoded.device_send_us is None


def test_sync_clock_ack_roundtrip() -> None:
    client_id = bytes.fromhex("aabbccddeeff")
    pkt = pack_ack_sync_clock(
        client_id,
        cmd_seq=101,
        device_receive_us=987_000,
        device_send_us=987_500,
        status=0,
    )

    decoded = parse_ack(pkt)

    assert decoded.client_id == client_id
    assert decoded.cmd_seq == 101
    assert decoded.status == 0
    assert decoded.device_receive_us == 987_000
    assert decoded.device_send_us == 987_500


def test_hello_ack_roundtrip() -> None:
    client_id = bytes.fromhex("aabbccddeeff")
    pkt = pack_hello_ack(client_id)

    assert pkt[0] == MSG_HELLO_ACK
    decoded = parse_hello_ack(pkt)
    assert decoded.client_id == client_id


def test_data_ack_roundtrip() -> None:
    client_id = bytes.fromhex("aabbccddeeff")
    pkt = pack_data_ack(client_id, last_seq_received=1234)

    assert pkt[0] == MSG_DATA_ACK
    decoded = parse_data_ack(pkt)
    assert decoded.client_id == client_id
    assert decoded.last_seq_received == 1234


def test_client_id_mac_roundtrip() -> None:
    client_id = bytes.fromhex("d05a01020304")

    mac = client_id_mac(client_id)

    assert mac == "d0:5a:01:02:03:04"
    assert parse_client_id(mac) == client_id
