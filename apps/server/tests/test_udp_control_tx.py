from __future__ import annotations

from pathlib import Path

import pytest

from vibesensor.protocol import HelloMessage, parse_cmd
from vibesensor.registry import ClientRegistry
from vibesensor.udp_control_tx import UDPControlPlane


class _DummyTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((data, addr))

    def close(self) -> None:
        return


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
) -> None:
    client_hex = "aabbccddeeff"
    registry = ClientRegistry(tmp_path / "clients.json")
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
    transport = _DummyTransport()
    plane.transport = transport  # type: ignore[assignment]

    ok, cmd_seq = plane.send_identify(client_id_input, 1500)

    assert ok is True
    assert isinstance(cmd_seq, int)
    assert transport.sent
    payload, addr = transport.sent[0]
    assert addr == ("127.0.0.1", 9010)

    cmd = parse_cmd(payload)
    assert cmd.client_id.hex() == client_hex


def test_send_data_ack_sends_to_control_addr(tmp_path: Path) -> None:
    client_hex = "aabbccddeeff"
    registry = ClientRegistry(tmp_path / "clients.json")
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
    transport = _DummyTransport()
    plane.transport = transport  # type: ignore[assignment]

    assert plane.send_data_ack(client_hex, 1234) is True
    assert len(transport.sent) == 1
    _, addr = transport.sent[0]
    assert addr == ("127.0.0.1", 9010)
