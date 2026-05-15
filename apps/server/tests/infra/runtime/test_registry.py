"""Registry identity, persisted naming, and location contracts."""

from __future__ import annotations

from pathlib import Path

from test_support.runtime_lifecycle import (
    FakeAckMessage as _FakeAckMessage,
)
from test_support.runtime_lifecycle import (
    FakeClientNameStore as _FakeClientNameStore,
)
from test_support.runtime_lifecycle import (
    FakeDataMessage as _FakeDataMessage,
)
from test_support.runtime_lifecycle import (
    FakeHelloMessage as _FakeHelloMessage,
)
from test_support.runtime_lifecycle import (
    build_history_db as _build_history_db,
)
from test_support.runtime_lifecycle import (
    build_registry as _build_registry,
)
from test_support.runtime_lifecycle import (
    make_hello_message as _make_hello_message,
)

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.adapters.udp.protocol import HelloMessage
from vibesensor.infra.runtime.registry import ClientRegistry
from vibesensor.shared.boundaries.clients import snapshot_for_api


def test_registry_accepts_protocol_shaped_messages() -> None:
    registry = ClientRegistry()
    client_id = bytes.fromhex("aabbccddeeff")
    hello = _FakeHelloMessage(
        client_id=client_id,
        control_port=9010,
        sample_rate_hz=800,
        name="node-1",
        firmware_version="fw",
    )
    registry.update_from_hello(hello, ("10.4.0.2", 9010), now=1.0)

    result = registry.update_from_data(
        _FakeDataMessage(client_id=client_id, seq=5, t0_us=10, sample_count=200),
        ("10.4.0.2", 50000),
        now=2.0,
    )
    registry.update_from_ack(
        _FakeAckMessage(client_id=client_id, cmd_seq=77, status=1),
        now=3.0,
    )

    record = registry.get("aabbccddeeff")
    assert record is not None
    assert result.is_duplicate is False
    assert record.frames_total == 1
    assert record.last_ack_cmd_seq == 77
    assert record.last_ack_status == 1


def test_registry_persists_names_with_protocol_shaped_store() -> None:
    store = _FakeClientNameStore()
    registry = ClientRegistry(db=store)
    registry.set_name("001122334455", "rear")

    reloaded = ClientRegistry(db=store)
    reloaded.update_from_hello(
        _FakeHelloMessage(
            client_id=bytes.fromhex("001122334455"),
            control_port=9011,
            sample_rate_hz=800,
            name="ignored",
            firmware_version="fw2",
        ),
        ("10.4.0.3", 9011),
        now=5.0,
    )

    row = snapshot_for_api(reloaded, now=5.0)[0]
    assert row["name"] == "rear"


def test_registry_rename_normalizes_client_id(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    registry = ClientRegistry(db=db.client_name_repository)
    lower_id = "001122334455"
    upper_id = lower_id.upper()

    registry.set_name(lower_id, "rear")
    registry.set_name(upper_id, "rear-updated")

    rows = snapshot_for_api(registry, now=1.0)
    assert len(rows) == 1
    assert rows[0]["id"] == lower_id
    assert rows[0]["name"] == "rear-updated"


def test_registry_persist_keeps_offline_names(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    registry = ClientRegistry(db=db.client_name_repository)
    offline_id = "001122334455"
    active_id = "aabbccddeeff"

    registry.set_name(offline_id, "offline-node")
    hello = HelloMessage(
        client_id=bytes.fromhex(active_id),
        control_port=9010,
        sample_rate_hz=800,
        name="active-node",
        firmware_version="fw",
    )
    registry.update_from_hello(hello, ("10.4.0.2", 9010), now=2.0)

    registry2 = ClientRegistry(db=db.client_name_repository)
    registry2.update_from_hello(hello, ("10.4.0.2", 9010), now=3.0)
    registry2.update_from_hello(
        HelloMessage(
            client_id=bytes.fromhex(offline_id),
            control_port=9011,
            sample_rate_hz=800,
            name="should-not-overwrite",
            firmware_version="fw",
        ),
        ("10.4.0.3", 9011),
        now=4.0,
    )

    rows = {row["id"]: row for row in snapshot_for_api(registry2, now=4.0)}
    assert rows[offline_id]["name"] == "offline-node"


def test_registry_hello_uses_advertised_control_port(tmp_path: Path) -> None:
    db = _build_history_db(tmp_path)
    registry = _build_registry(db=db)
    hello = _make_hello_message(
        control_port=9010,
        name="node",
        firmware_version="fw",
        frame_samples=200,
    )
    registry.update_from_hello(hello, ("10.4.0.2", 54321), now=1.0)

    record = registry.get("aabbccddeeff")
    assert record is not None
    assert record.control_addr == ("10.4.0.2", 9010)

    row = snapshot_for_api(registry, now=1.0)[0]
    assert row["frame_samples"] == 200


def test_registry_remove_client_clears_persisted_entry(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    registry = ClientRegistry(db=db.client_name_repository)
    client_id = "001122334455"
    registry.set_name(client_id, "front-left")

    assert registry.remove_client(client_id) is True
    assert registry.remove_client(client_id) is False

    registry2 = ClientRegistry(db=db.client_name_repository)
    rows = snapshot_for_api(registry2, now=1.0)
    assert rows == []


def test_registry_clear_name_reverts_to_default(tmp_path: Path) -> None:
    """clear_name() should remove the user-assigned name and revert to default."""
    db = create_history_persistence_adapters(tmp_path / "history.db")
    registry = ClientRegistry(db=db.client_name_repository)
    client_id = "001122334455"

    # Assign a user name
    registry.set_name(client_id, "Front Left Wheel")
    record = registry.get(client_id)
    assert record is not None
    assert record.name == "Front Left Wheel"

    # Clear the name
    cleared = registry.clear_name(client_id)
    assert cleared.name == f"client-{client_id[-4:]}"
    row = snapshot_for_api(registry, now=1.0)[0]
    assert row["id"] == client_id
    assert row["name"] == f"client-{client_id[-4:]}"

    # Verify persistence: the cleared name should NOT come back after reload
    assert db.client_name_repository.list_client_names() == {}
    registry2 = ClientRegistry(db=db.client_name_repository)
    assert snapshot_for_api(registry2, now=1.0) == []


def test_registry_clear_name_preserves_other_clients(tmp_path: Path) -> None:
    """Clearing one client's name should not affect other clients."""
    db = create_history_persistence_adapters(tmp_path / "history.db")
    registry = ClientRegistry(db=db.client_name_repository)

    registry.set_name("001122334455", "Front Left Wheel")
    registry.set_name("aabbccddeeff", "Rear Right Wheel")

    registry.clear_name("001122334455")

    record_other = registry.get("aabbccddeeff")
    assert record_other is not None
    assert record_other.name == "Rear Right Wheel"


def test_set_location_populates_client_record(tmp_path: Path) -> None:
    """set_location must write to ClientRecord so snapshot_for_api returns it."""
    db = create_history_persistence_adapters(tmp_path / "history.db")
    registry = ClientRegistry(db=db.client_name_repository)
    client_id = bytes.fromhex("aabbccddeeff")

    hello = HelloMessage(
        client_id=client_id,
        control_port=9010,
        sample_rate_hz=800,
        name="node-1",
        firmware_version="fw",
    )
    registry.update_from_hello(hello, ("10.4.0.2", 9010), now=1.0)

    hex_id = "aabbccddeeff"
    # Before assignment: location should be empty
    row_before = snapshot_for_api(registry, now=1.0)[0]
    assert row_before["location_code"] == ""

    # Assign location
    record = registry.set_location(hex_id, "front_left_wheel")
    assert record.location_code == "front_left_wheel"

    # After assignment: snapshot must expose the location
    row_after = snapshot_for_api(registry, now=2.0)[0]
    assert row_after["location_code"] == "front_left_wheel"


def test_set_location_trims_whitespace(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    registry = ClientRegistry(db=db.client_name_repository)
    hex_id = "001122334455"
    registry.set_location(hex_id, "  rear_axle  ")
    row = snapshot_for_api(registry, now=1.0)[0]
    assert row["location_code"] == "rear_axle"


# ---------------------------------------------------------------------------
# Deduplication tests (R3)
# ---------------------------------------------------------------------------
