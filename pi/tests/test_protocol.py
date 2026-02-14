from __future__ import annotations

import numpy as np

from vibesensor.protocol import (
    CMD_IDENTIFY,
    MSG_DATA,
    MSG_HELLO,
    pack_cmd_identify,
    pack_data,
    pack_hello,
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

