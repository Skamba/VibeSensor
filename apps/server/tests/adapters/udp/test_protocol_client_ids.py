"""UDP protocol client-id helper contracts."""

from __future__ import annotations

import numpy as np
import pytest

from vibesensor.adapters.udp.protocol import (
    client_id_hex,
    client_id_mac,
    extract_client_id_hex,
    pack_data,
    pack_hello,
    parse_client_id,
)


def test_parse_client_id_accepts_colon_separated_uppercase_hex() -> None:
    assert parse_client_id("AA:BB:CC:DD:EE:FF") == bytes.fromhex("aabbccddeeff")


def test_extract_client_id_hex_from_data_packet() -> None:
    client_id = bytes.fromhex("a1b2c3d4e5f6")
    pkt = pack_data(client_id, seq=1, t0_us=0, samples=np.zeros((1, 3), dtype="<i2"))

    assert extract_client_id_hex(pkt) == "a1b2c3d4e5f6"


def test_extract_client_id_hex_from_hello() -> None:
    client_id = bytes.fromhex("112233445566")
    pkt = pack_hello(client_id, control_port=9000, sample_rate_hz=800, name="test")

    assert extract_client_id_hex(pkt) == "112233445566"


@pytest.mark.parametrize("data", [b"\x01\x01", b"", b"\x01\x01\xaa\xbb"])
def test_extract_client_id_hex_too_short(data: bytes) -> None:
    assert extract_client_id_hex(data) is None


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
