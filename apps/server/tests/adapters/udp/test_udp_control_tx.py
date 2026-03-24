from __future__ import annotations

import logging
from pathlib import Path

import pytest

from vibesensor.adapters.persistence.history_db import HistoryDB
from vibesensor.adapters.udp.protocol import HelloMessage, pack_ack, parse_cmd
from vibesensor.adapters.udp.udp_control_tx import ControlDatagramProtocol, UDPControlPlane
from vibesensor.infra.runtime.registry import ClientRegistry


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
    registry = ClientRegistry(db=HistoryDB(tmp_path / "history.db"))
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


def test_control_datagram_unexpected_exception_is_logged_and_counted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client_hex = "aabbccddeeff"
    registry = ClientRegistry(db=HistoryDB(tmp_path / "history.db"))
    protocol = ControlDatagramProtocol(registry)
    packet = pack_ack(bytes.fromhex(client_hex), cmd_seq=7, status=0)

    def boom(_: bytes) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr("vibesensor.adapters.udp.udp_control_tx.parse_ack", boom)

    with caplog.at_level(logging.WARNING):
        protocol.datagram_received(packet, ("127.0.0.1", 9001))

    record = registry.get(client_hex)
    assert record is not None
    assert record.parse_errors == 1
    assert "Unexpected error processing control datagram" in caplog.text


def test_close_closes_transport_once_and_clears_reference(tmp_path: Path, fake_transport) -> None:
    registry = ClientRegistry(db=HistoryDB(tmp_path / "history.db"))
    plane = UDPControlPlane(registry=registry, bind_host="127.0.0.1", bind_port=9001)
    plane.transport = fake_transport

    plane.close()

    assert fake_transport.closed is True
    assert plane.transport is None

    plane.close()

    assert fake_transport.closed is True
    assert plane.transport is None
