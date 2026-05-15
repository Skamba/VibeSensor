"""UDP protocol parser and packer validation edges."""

from __future__ import annotations

import logging
import struct
from collections.abc import Callable

import numpy as np
import pytest

from vibesensor.adapters.udp.protocol import (
    ACK_STRUCT,
    CMD_HEADER_BYTES,
    DATA_ACK_STRUCT,
    DATA_HEADER_BYTES,
    HELLO_ACK_STRUCT,
    HELLO_BASE,
    HELLO_CAP_EXPLICIT_ACK,
    HELLO_FIXED_BYTES,
    MSG_HELLO,
    pack_ack,
    pack_cmd_identify,
    pack_cmd_sync_clock,
    pack_data,
    pack_hello,
    parse_ack,
    parse_cmd,
    parse_data,
    parse_data_ack,
    parse_hello,
    parse_hello_ack,
)
from vibesensor.shared.exceptions import ProtocolError


def test_parse_hello_rejects_missing_capabilities() -> None:
    client_id = bytes.fromhex("a1b2c3d4e5f6")
    legacy_packet = pack_hello(
        client_id=client_id,
        control_port=9123,
        sample_rate_hz=800,
        name="front-left",
        frame_samples=200,
        firmware_version="fw-test",
        queue_overflow_drops=7,
        capabilities=HELLO_CAP_EXPLICIT_ACK,
    )[:-1]

    with pytest.raises(ProtocolError, match="HELLO missing capabilities"):
        parse_hello(legacy_packet)


@pytest.mark.parametrize(
    ("parse_fn", "short_data", "match"),
    [
        (parse_hello, b"\x01", "HELLO too short"),
        (parse_data, b"\x02\x01", "DATA too short"),
        (parse_cmd, b"\x03\x01", "CMD too short"),
    ],
    ids=["hello", "data", "cmd"],
)
def test_parse_too_short(parse_fn, short_data: bytes, match: str) -> None:
    with pytest.raises(ProtocolError, match=match):
        parse_fn(short_data)


@pytest.mark.parametrize(
    ("parse_fn", "data", "match"),
    [
        (
            parse_hello,
            b"\xff\x01" + b"\x00" * (HELLO_FIXED_BYTES - 2),
            "Invalid HELLO header",
        ),
        (
            parse_data,
            b"\xff\x01" + b"\x00" * (DATA_HEADER_BYTES - 2),
            "Invalid DATA header",
        ),
        (
            parse_cmd,
            b"\xff\x01" + b"\x00" * (CMD_HEADER_BYTES - 2),
            "Invalid CMD header",
        ),
        (
            parse_ack,
            ACK_STRUCT.pack(0xFF, 0x01, b"\x00" * 6, 0, 0),
            "Invalid ACK header",
        ),
        (
            parse_data_ack,
            DATA_ACK_STRUCT.pack(0xFF, 0x01, b"\x00" * 6, 0),
            "Invalid DATA_ACK header",
        ),
        (
            parse_hello_ack,
            HELLO_ACK_STRUCT.pack(0xFF, 0x01, b"\x00" * 6),
            "Invalid HELLO_ACK header",
        ),
    ],
    ids=["hello", "data", "cmd", "ack", "data_ack", "hello_ack"],
)
def test_parse_rejects_invalid_headers(
    parse_fn: Callable[[bytes], object],
    data: bytes,
    match: str,
) -> None:
    with pytest.raises(ProtocolError, match=match):
        parse_fn(data)


def test_parse_hello_missing_name() -> None:
    client_id = bytes.fromhex("aabbccddeeff")
    header = pack_hello(client_id, 9000, 800, "test")
    truncated = header[: HELLO_BASE.size]
    truncated = truncated[:-1] + b"\xff"

    with pytest.raises(ProtocolError, match="HELLO missing name"):
        parse_hello(truncated)


def test_parse_hello_firmware_length_out_of_range() -> None:
    client_id = bytes.fromhex("aabbccddeeff")
    pkt = bytearray(pack_hello(client_id, 9000, 800, "test", firmware_version=""))

    fw_len_offset = HELLO_BASE.size + len("test")
    pkt[fw_len_offset] = 10
    truncated_fw = bytes(pkt[: fw_len_offset + 2])
    with pytest.raises(ProtocolError, match="firmware length out of range"):
        parse_hello(truncated_fw)


def test_parse_data_payload_size_mismatch() -> None:
    client_id = bytes.fromhex("010203040506")
    samples = np.zeros((1, 3), dtype="<i2")
    pkt = pack_data(client_id, seq=1, t0_us=0, samples=samples)

    with pytest.raises(ProtocolError, match="payload size mismatch"):
        parse_data(pkt[:-1])


def test_pack_data_rejects_wrong_shape() -> None:
    client_id = bytes.fromhex("010203040506")
    bad_samples = np.array([1, 2, 3], dtype=np.int16)

    with pytest.raises(ValueError, match="shaped.*N.*3"):
        pack_data(client_id, seq=1, t0_us=0, samples=bad_samples)


@pytest.mark.parametrize(
    ("parse_fn", "short_data", "match"),
    [
        (parse_ack, b"\x04\x01\x00", "ACK too short"),
        (parse_data_ack, b"\x05\x01\x00", "DATA_ACK has unexpected size"),
        (parse_hello_ack, b"\x06\x01\x00", "HELLO_ACK has unexpected size"),
    ],
    ids=["ack", "data_ack", "hello_ack"],
)
def test_parse_wrong_size(parse_fn, short_data: bytes, match: str) -> None:
    with pytest.raises(ProtocolError, match=match):
        parse_fn(short_data)


def test_parse_ack_rejects_unknown_extended_size() -> None:
    pkt = pack_ack(bytes.fromhex("aabbccddeeff"), cmd_seq=7, status=0) + b"\x00"

    with pytest.raises(ProtocolError, match="ACK has unexpected size"):
        parse_ack(pkt)


def test_parse_hello_rejects_zero_sample_rate() -> None:
    client_id = bytes.fromhex("aabbccddeeff")
    name_bytes = b"sensor"
    raw = HELLO_BASE.pack(MSG_HELLO, 1, client_id, 9000, 0, 200, len(name_bytes))
    raw += name_bytes + bytes([0]) + struct.pack("<I", 0) + bytes([HELLO_CAP_EXPLICIT_ACK])

    with pytest.raises(ProtocolError, match="sample_rate_hz must not be zero"):
        parse_hello(raw)


def test_parse_hello_warns_on_zero_control_port(caplog: pytest.LogCaptureFixture) -> None:
    client_id = bytes.fromhex("aabbccddeeff")
    name_bytes = b"sensor"
    raw = HELLO_BASE.pack(MSG_HELLO, 1, client_id, 0, 800, 200, len(name_bytes))
    raw += name_bytes + bytes([0]) + struct.pack("<I", 0) + bytes([HELLO_CAP_EXPLICIT_ACK])

    with caplog.at_level(logging.WARNING, logger="vibesensor.adapters.udp.protocol"):
        msg = parse_hello(raw)

    assert msg.control_port == 0
    assert any("control_port is 0" in r.message for r in caplog.records)


def test_pack_hello_rejects_wrong_client_id_length() -> None:
    with pytest.raises(ValueError, match="client_id must be 6 bytes"):
        pack_hello(b"\x01\x02\x03", 9000, 800, "test")


def test_pack_data_rejects_empty_samples() -> None:
    client_id = bytes.fromhex("aabbccddeeff")
    with pytest.raises(ValueError, match="must not be empty"):
        pack_data(client_id, seq=1, t0_us=0, samples=np.zeros((0, 3), dtype="<i2"))


def test_parse_cmd_rejects_unknown_cmd_id() -> None:
    client_id = bytes.fromhex("aabbccddeeff")
    raw = struct.pack("<BB6sBI", 3, 1, client_id, 99, 42)

    with pytest.raises(ProtocolError, match="unsupported cmd_id=99"):
        parse_cmd(raw)


def test_pack_cmd_identify_rejects_negative_cmd_seq() -> None:
    client_id = bytes.fromhex("aabbccddeeff")
    with pytest.raises(ValueError, match="cmd_seq must be non-negative"):
        pack_cmd_identify(client_id, cmd_seq=-1, duration_ms=500)


def test_pack_cmd_sync_clock_rejects_negative_cmd_seq() -> None:
    client_id = bytes.fromhex("aabbccddeeff")
    with pytest.raises(ValueError, match="cmd_seq must be non-negative"):
        pack_cmd_sync_clock(client_id, cmd_seq=-5, server_time_us=1_000_000)


def test_pack_ack_rejects_negative_cmd_seq() -> None:
    client_id = bytes.fromhex("aabbccddeeff")
    with pytest.raises(ValueError, match="cmd_seq must be non-negative"):
        pack_ack(client_id, cmd_seq=-1)
