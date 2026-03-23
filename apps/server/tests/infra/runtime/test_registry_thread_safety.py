from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from vibesensor.adapters.udp.protocol import HelloMessage
from vibesensor.infra.runtime.registry import ClientRecordSnapshot, ClientRegistry


def _make_registry_with_client() -> tuple[ClientRegistry, str]:
    registry = ClientRegistry()
    client_id = "aabbccddeeff"
    registry.update_from_hello(
        HelloMessage(
            client_id=bytes.fromhex(client_id),
            control_port=9010,
            sample_rate_hz=800,
            name="node-1",
            firmware_version="fw-1",
            frame_samples=200,
        ),
        ("10.4.0.2", 9010),
        now=1.0,
        now_mono=1.0,
    )
    return registry, client_id


def test_registry_get_returns_frozen_snapshot() -> None:
    registry, client_id = _make_registry_with_client()

    record = registry.get(client_id)

    assert isinstance(record, ClientRecordSnapshot)
    assert record is not None
    assert record.control_addr == ("10.4.0.2", 9010)
    with pytest.raises(FrozenInstanceError):
        record.name = "mutated"


def test_registry_get_returns_point_in_time_snapshot() -> None:
    registry, client_id = _make_registry_with_client()

    first = registry.get(client_id)
    assert first is not None

    registry.set_name(client_id, "renamed-node")
    registry.set_location(client_id, "front-left")

    second = registry.get(client_id)
    assert second is not None

    assert first.name == "node-1"
    assert first.location_code == ""
    assert second.name == "renamed-node"
    assert second.location_code == "front-left"
