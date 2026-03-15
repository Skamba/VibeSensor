from __future__ import annotations

import numpy as np
import pytest

from vibesensor.adapters.udp.protocol import (
    ACK_BYTES,
    ACK_STRUCT,
    CMD_HEADER_BYTES,
    CMD_IDENTIFY,
    CMD_IDENTIFY_BYTES,
    CMD_SYNC_CLOCK,
    DATA_ACK_BYTES,
    DATA_ACK_STRUCT,
    DATA_HEADER_BYTES,
    HELLO_BASE,
    HELLO_FIXED_BYTES,
    MSG_DATA,
    MSG_DATA_ACK,
    MSG_HELLO,
    ProtocolError,
    client_id_hex,
    client_id_mac,
    extract_client_id_hex,
    pack_ack,
    pack_cmd_identify,
    pack_cmd_sync_clock,
    pack_data,
    pack_data_ack,
    pack_hello,
    parse_ack,
    parse_client_id,
    parse_cmd,
    parse_data,
    parse_data_ack,
    parse_hello,
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


def test_pack_cmd_identify_clamps_duration_bounds() -> None:
    client_id = bytes.fromhex("112233445566")
    low = parse_cmd(pack_cmd_identify(client_id, cmd_seq=1, duration_ms=0))
    high = parse_cmd(pack_cmd_identify(client_id, cmd_seq=2, duration_ms=999999))
    assert int.from_bytes(low.params[:2], "little") == 1
    assert int.from_bytes(high.params[:2], "little") == 60_000


def test_pack_cmd_sync_clock_clamps_negative_server_time() -> None:
    client_id = bytes.fromhex("112233445566")
    parsed = parse_cmd(pack_cmd_sync_clock(client_id, cmd_seq=7, server_time_us=-123))
    assert parsed.cmd_id == CMD_SYNC_CLOCK
    assert parsed.cmd_seq == 7
    assert int.from_bytes(parsed.params[:8], "little") == 0


def test_client_id_mac_roundtrip() -> None:
    client_id = bytes.fromhex("d05a01020304")
    mac = client_id_mac(client_id)
    assert mac == "d0:5a:01:02:03:04"
    assert parse_client_id(mac) == client_id


def test_parse_client_id_accepts_colon_separated_uppercase_hex() -> None:
    assert parse_client_id("AA:BB:CC:DD:EE:FF") == bytes.fromhex("aabbccddeeff")


def test_protocol_layout_constants_match_esp_side() -> None:
    assert HELLO_FIXED_BYTES == 20
    assert DATA_HEADER_BYTES == 22
    assert ACK_BYTES == 13
    assert DATA_ACK_BYTES == 12
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


@pytest.mark.parametrize("data", [b"\x01\x01", b"", b"\x01\x01\xaa\xbb"])
def test_extract_client_id_hex_too_short(data) -> None:
    assert extract_client_id_hex(data) is None


# ---------------------------------------------------------------------------
# Error path tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fn", "arg", "match"),
    [
        (client_id_hex, b"\x01\x02", "6 bytes"),
        (client_id_mac, b"\x01\x02\x03", "6 bytes"),
        (parse_client_id, "abcd", "12 hex chars"),
    ],
    ids=["hex", "mac", "parse"],
)
def test_client_id_rejects_wrong_length(fn, arg, match) -> None:
    with pytest.raises(ValueError, match=match):
        fn(arg)


@pytest.mark.parametrize(
    ("parse_fn", "short_data", "match"),
    [
        (parse_hello, b"\x01", "HELLO too short"),
        (parse_data, b"\x02\x01", "DATA too short"),
        (parse_cmd, b"\x03\x01", "CMD too short"),
    ],
    ids=["hello", "data", "cmd"],
)
def test_parse_too_short(parse_fn, short_data, match) -> None:
    with pytest.raises(ProtocolError, match=match):
        parse_fn(short_data)


@pytest.mark.parametrize(
    ("parse_fn", "header_bytes", "match"),
    [
        (parse_hello, HELLO_FIXED_BYTES, "Invalid HELLO header"),
        (parse_data, DATA_HEADER_BYTES, "Invalid DATA header"),
        (parse_cmd, CMD_HEADER_BYTES, "Invalid CMD header"),
    ],
    ids=["hello", "data", "cmd"],
)
def test_parse_invalid_header(parse_fn, header_bytes, match) -> None:
    data = b"\xff\x01" + b"\x00" * (header_bytes - 2)
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


def test_pack_hello_truncates_name_and_firmware_to_32_bytes() -> None:
    client_id = bytes.fromhex("010203040506")
    decoded = parse_hello(pack_hello(client_id, 9000, 800, "n" * 64, firmware_version="f" * 64))
    assert decoded.name == "n" * 32
    assert decoded.firmware_version == "f" * 32


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


def test_ack_roundtrip() -> None:
    client_id = bytes.fromhex("aabbccddeeff")
    pkt = pack_ack(client_id, cmd_seq=99, status=0)
    decoded = parse_ack(pkt)
    assert decoded.client_id == client_id
    assert decoded.cmd_seq == 99
    assert decoded.status == 0


@pytest.mark.parametrize(
    ("parse_fn", "short_data", "match"),
    [
        (parse_ack, b"\x04\x01\x00", "ACK has unexpected size"),
        (parse_data_ack, b"\x05\x01\x00", "DATA_ACK has unexpected size"),
    ],
    ids=["ack", "data_ack"],
)
def test_parse_wrong_size(parse_fn, short_data, match) -> None:
    with pytest.raises(ProtocolError, match=match):
        parse_fn(short_data)


@pytest.mark.parametrize(
    ("struct", "parse_fn", "pack_args", "match"),
    [
        (ACK_STRUCT, parse_ack, (0xFF, 0x01, b"\x00" * 6, 0, 0), "Invalid ACK header"),
        (DATA_ACK_STRUCT, parse_data_ack, (0xFF, 0x01, b"\x00" * 6, 0), "Invalid DATA_ACK header"),
    ],
    ids=["ack", "data_ack"],
)
def test_parse_ack_invalid_header(struct, parse_fn, pack_args, match) -> None:
    pkt = struct.pack(*pack_args)
    with pytest.raises(ProtocolError, match=match):
        parse_fn(pkt)


def test_data_ack_roundtrip() -> None:
    client_id = bytes.fromhex("aabbccddeeff")
    pkt = pack_data_ack(client_id, last_seq_received=1234)
    assert pkt[0] == MSG_DATA_ACK
    decoded = parse_data_ack(pkt)
    assert decoded.client_id == client_id
    assert decoded.last_seq_received == 1234


# ---------------------------------------------------------------------------
# Wave 3 Bruno3 — new validation fixes
# ---------------------------------------------------------------------------


def test_parse_hello_rejects_zero_sample_rate() -> None:
    """parse_hello must raise ProtocolError when sample_rate_hz == 0 (Fix 1)."""
    client_id = bytes.fromhex("aabbccddeeff")
    # Build a raw HELLO packet with sample_rate_hz=0 manually.
    name_bytes = b"sensor"
    import struct as _struct

    raw = HELLO_BASE.pack(MSG_HELLO, 1, client_id, 9000, 0, 200, len(name_bytes))
    raw += name_bytes + bytes([0]) + _struct.pack("<I", 0)
    with pytest.raises(ProtocolError, match="sample_rate_hz must not be zero"):
        parse_hello(raw)


def test_parse_hello_warns_on_zero_control_port(caplog: pytest.LogCaptureFixture) -> None:
    """parse_hello must log a warning when control_port == 0 (Fix 2)."""
    import logging
    import struct as _struct

    client_id = bytes.fromhex("aabbccddeeff")
    name_bytes = b"sensor"
    raw = HELLO_BASE.pack(MSG_HELLO, 1, client_id, 0, 800, 200, len(name_bytes))
    raw += name_bytes + bytes([0]) + _struct.pack("<I", 0)
    with caplog.at_level(logging.WARNING, logger="vibesensor.adapters.udp.protocol"):
        msg = parse_hello(raw)
    assert msg.control_port == 0
    assert any("control_port is 0" in r.message for r in caplog.records)


def test_pack_hello_rejects_wrong_client_id_length() -> None:
    """pack_hello must raise ValueError when client_id is not exactly 6 bytes (Fix 3)."""
    with pytest.raises(ValueError, match="client_id must be 6 bytes"):
        pack_hello(b"\x01\x02\x03", 9000, 800, "test")


def test_pack_data_rejects_empty_samples() -> None:
    """pack_data must raise ValueError for a zero-row samples array (Fix 4)."""
    client_id = bytes.fromhex("aabbccddeeff")
    with pytest.raises(ValueError, match="must not be empty"):
        pack_data(client_id, seq=1, t0_us=0, samples=np.zeros((0, 3), dtype="<i2"))


def test_parse_cmd_warns_on_unknown_cmd_id(caplog: pytest.LogCaptureFixture) -> None:
    """parse_cmd must log a warning for an unrecognized cmd_id (Fix 5)."""
    import logging
    import struct as _struct

    client_id = bytes.fromhex("aabbccddeeff")
    # Build a CMD header with cmd_id=99 (unknown)
    raw = _struct.pack("<BB6sBI", 3, 1, client_id, 99, 42)
    with caplog.at_level(logging.WARNING, logger="vibesensor.adapters.udp.protocol"):
        cmd = parse_cmd(raw)
    assert cmd.cmd_id == 99
    assert any("unrecognized cmd_id" in r.message for r in caplog.records)


def test_pack_cmd_identify_rejects_negative_cmd_seq() -> None:
    """pack_cmd_identify must raise ValueError for cmd_seq < 0 (Fix 6)."""
    client_id = bytes.fromhex("aabbccddeeff")
    with pytest.raises(ValueError, match="cmd_seq must be non-negative"):
        pack_cmd_identify(client_id, cmd_seq=-1, duration_ms=500)


def test_pack_cmd_sync_clock_rejects_negative_cmd_seq() -> None:
    """pack_cmd_sync_clock must raise ValueError for cmd_seq < 0 (Fix 7)."""
    client_id = bytes.fromhex("aabbccddeeff")
    with pytest.raises(ValueError, match="cmd_seq must be non-negative"):
        pack_cmd_sync_clock(client_id, cmd_seq=-5, server_time_us=1_000_000)


def test_pack_ack_rejects_negative_cmd_seq() -> None:
    """pack_ack must raise ValueError for cmd_seq < 0 (Fix 8)."""
    client_id = bytes.fromhex("aabbccddeeff")
    with pytest.raises(ValueError, match="cmd_seq must be non-negative"):
        pack_ack(client_id, cmd_seq=-1)
