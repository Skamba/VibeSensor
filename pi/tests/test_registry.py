from __future__ import annotations

from pathlib import Path

import numpy as np

from vibesensor.protocol import DataMessage, HelloMessage
from vibesensor.registry import ClientRegistry


def test_registry_sequence_gap(tmp_path: Path) -> None:
    registry = ClientRegistry(tmp_path / "clients.json")
    client_id = bytes.fromhex("aabbccddeeff")

    hello = HelloMessage(
        client_id=client_id,
        control_port=9010,
        sample_rate_hz=800,
        name="node-1",
        firmware_version="fw",
    )
    registry.update_from_hello(hello, ("192.168.4.2", 9010), now=1.0)

    samples = np.zeros((200, 3), dtype=np.int16)
    msg0 = DataMessage(client_id=client_id, seq=0, t0_us=10, sample_count=200, samples=samples)
    msg1 = DataMessage(client_id=client_id, seq=2, t0_us=20, sample_count=200, samples=samples)
    registry.update_from_data(msg0, ("192.168.4.2", 50000), now=2.0)
    registry.update_from_data(msg1, ("192.168.4.2", 50000), now=3.0)

    row = registry.snapshot_for_api(now=3.0)[0]
    assert row["frames_total"] == 2
    assert row["dropped_frames"] == 1


def test_registry_rename_persist(tmp_path: Path) -> None:
    persist = tmp_path / "clients.json"
    registry = ClientRegistry(persist)
    client_id = "001122334455"
    registry.set_name(client_id, "rear")

    registry2 = ClientRegistry(persist)
    hello = HelloMessage(
        client_id=bytes.fromhex(client_id),
        control_port=9011,
        sample_rate_hz=800,
        name="ignored",
        firmware_version="fw2",
    )
    registry2.update_from_hello(hello, ("192.168.4.3", 9011), now=5.0)

    row = registry2.snapshot_for_api(now=5.0)[0]
    assert row["name"] == "rear"


