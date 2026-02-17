from __future__ import annotations

import numpy as np
import pytest

from vibesensor.protocol import (
    ACK_BYTES,
    CMD_HEADER_BYTES,
    CMD_IDENTIFY,
    CMD_IDENTIFY_BYTES,
    DATA_HEADER_BYTES,
    HELLO_FIXED_BYTES,
    MSG_DATA,
    MSG_HELLO,
    ProtocolError,
    client_id_hex,
    client_id_mac,
    extract_client_id_hex,
    pack_ack,
    pack_cmd_identify,
    pack_data,
    pack_hello,
    parse_ack,
    parse_client_id,
    parse_cmd,
    parse_data,
    parse_hello,
)


def test_hello_roundtrip() -> None:
    client_id = bytes.fromhex("a1b2c3d4e5f6")
    pkt = pack_hello(
        client_id=client_id,
        control_port=9123,
        sample_rate_hz=800,
        name="front-left",
        firmware_version="fw-test",
        queue_overflow_drops=7,
    )
    assert pkt[0] == MSG_HELLO
    decoded = parse_hello(pkt)
    assert decoded.client_id == client_id
    assert decoded.control_port == 9123
    assert decoded.sample_rate_hz == 800
    assert decoded.name == "front-left"
    assert decoded.firmware_version == "fw-test"
    assert decoded.queue_overflow_drops == 7


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


def test_parse_identify_cmd() -> None:
    client_id = bytes.fromhex("112233445566")
    cmd = pack_cmd_identify(client_id, cmd_seq=42, duration_ms=1500)
    parsed = parse_cmd(cmd)
    assert parsed.client_id == client_id
    assert parsed.cmd_id == CMD_IDENTIFY
    assert parsed.cmd_seq == 42
    assert int.from_bytes(parsed.params[:2], "little") == 1500


def test_client_id_mac_roundtrip() -> None:
    client_id = bytes.fromhex("d05a01020304")
    mac = client_id_mac(client_id)
    assert mac == "d0:5a:01:02:03:04"
    assert parse_client_id(mac) == client_id


def test_protocol_layout_constants_match_esp_side() -> None:
    assert HELLO_FIXED_BYTES == 18
    assert DATA_HEADER_BYTES == 22
    assert ACK_BYTES == 13
    assert CMD_HEADER_BYTES == 13
    assert CMD_IDENTIFY_BYTES == 15


# ---------------------------------------------------------------------------
# extract_client_id_hex
# ---------------------------------------------------------------------------


def test_extract_client_id_hex_from_data_packet() -> None:
    client_id = bytes.fromhex("a1b2c3d4e5f6")
    pkt = pack_data(client_id, seq=1, t0_us=0, samples=np.zeros((1, 3), dtype="<i2"))
    assert extract_client_id_hex(pkt) == "a1b2c3d4e5f6"


def test_extract_client_id_hex_from_hello() -> None:
    client_id = bytes.fromhex("112233445566")
    pkt = pack_hello(client_id, control_port=9000, sample_rate_hz=800, name="test")
    assert extract_client_id_hex(pkt) == "112233445566"


def test_extract_client_id_hex_too_short() -> None:
    assert extract_client_id_hex(b"\x01\x01") is None
    assert extract_client_id_hex(b"") is None
    assert extract_client_id_hex(b"\x01\x01\xaa\xbb") is None


# ---------------------------------------------------------------------------
# Error path tests
# ---------------------------------------------------------------------------


def test_client_id_hex_rejects_wrong_length() -> None:
    with pytest.raises(ValueError, match="6 bytes"):
        client_id_hex(b"\x01\x02")


def test_client_id_mac_rejects_wrong_length() -> None:
    with pytest.raises(ValueError, match="6 bytes"):
        client_id_mac(b"\x01\x02\x03")


def test_parse_client_id_rejects_wrong_length() -> None:
    with pytest.raises(ValueError, match="12 hex chars"):
        parse_client_id("abcd")


def test_parse_hello_too_short() -> None:
    with pytest.raises(ProtocolError, match="HELLO too short"):
        parse_hello(b"\x01")


def test_parse_hello_invalid_header() -> None:
    # Valid length but wrong msg_type
    data = b"\xff\x01" + b"\x00" * (HELLO_FIXED_BYTES - 2)
    with pytest.raises(ProtocolError, match="Invalid HELLO header"):
        parse_hello(data)


def test_parse_hello_missing_name() -> None:
    # Build a hello where name_len says 200 but only 0 bytes remain
    client_id = bytes.fromhex("aabbccddeeff")
    header = pack_hello(client_id, 9000, 800, "test")
    # Truncate after name_len
    from vibesensor.protocol import HELLO_BASE

    truncated = header[: HELLO_BASE.size]
    # Patch name_len to something too large
    truncated = truncated[:-1] + b"\xff"
    with pytest.raises(ProtocolError, match="HELLO missing name"):
        parse_hello(truncated)


def test_parse_data_too_short() -> None:
    with pytest.raises(ProtocolError, match="DATA too short"):
        parse_data(b"\x02\x01")


def test_parse_data_invalid_header() -> None:
    data = b"\xff\x01" + b"\x00" * (DATA_HEADER_BYTES - 2)
    with pytest.raises(ProtocolError, match="Invalid DATA header"):
        parse_data(data)


def test_parse_data_payload_size_mismatch() -> None:
    # Build a valid data header with sample_count=1 but no payload
    client_id = bytes.fromhex("010203040506")
    samples = np.zeros((1, 3), dtype="<i2")
    pkt = pack_data(client_id, seq=1, t0_us=0, samples=samples)
    # Truncate payload
    with pytest.raises(ProtocolError, match="payload size mismatch"):
        parse_data(pkt[:-1])


def test_pack_data_rejects_wrong_shape() -> None:
    client_id = bytes.fromhex("010203040506")
    bad_samples = np.array([1, 2, 3], dtype=np.int16)
    with pytest.raises(ValueError, match="shaped.*N.*3"):
        pack_data(client_id, seq=1, t0_us=0, samples=bad_samples)


def test_parse_cmd_too_short() -> None:
    with pytest.raises(ProtocolError, match="CMD too short"):
        parse_cmd(b"\x03\x01")


def test_parse_cmd_invalid_header() -> None:
    data = b"\xff\x01" + b"\x00" * (CMD_HEADER_BYTES - 2)
    with pytest.raises(ProtocolError, match="Invalid CMD header"):
        parse_cmd(data)


def test_ack_roundtrip() -> None:
    client_id = bytes.fromhex("aabbccddeeff")
    pkt = pack_ack(client_id, cmd_seq=99, status=0)
    decoded = parse_ack(pkt)
    assert decoded.client_id == client_id
    assert decoded.cmd_seq == 99
    assert decoded.status == 0


def test_parse_ack_wrong_size() -> None:
    with pytest.raises(ProtocolError, match="ACK has unexpected size"):
        parse_ack(b"\x04\x01\x00")


def test_parse_ack_invalid_header() -> None:
    from vibesensor.protocol import ACK_STRUCT

    pkt = ACK_STRUCT.pack(0xFF, 0x01, b"\x00" * 6, 0, 0)
    with pytest.raises(ProtocolError, match="Invalid ACK header"):
        parse_ack(pkt)
