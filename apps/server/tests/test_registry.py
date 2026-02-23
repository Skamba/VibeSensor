from __future__ import annotations

from pathlib import Path

import numpy as np

from vibesensor.history_db import HistoryDB
from vibesensor.protocol import DataMessage, HelloMessage
from vibesensor.registry import ClientRegistry


def test_registry_sequence_gap(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db)
    client_id = bytes.fromhex("aabbccddeeff")

    hello = HelloMessage(
        client_id=client_id,
        control_port=9010,
        sample_rate_hz=800,
        name="node-1",
        firmware_version="fw",
    )
    registry.update_from_hello(hello, ("10.4.0.2", 9010), now=1.0)

    samples = np.zeros((200, 3), dtype=np.int16)
    msg0 = DataMessage(client_id=client_id, seq=0, t0_us=10, sample_count=200, samples=samples)
    msg1 = DataMessage(client_id=client_id, seq=2, t0_us=20, sample_count=200, samples=samples)
    registry.update_from_data(msg0, ("10.4.0.2", 50000), now=2.0)
    registry.update_from_data(msg1, ("10.4.0.2", 50000), now=3.0)

    row = registry.snapshot_for_api(now=3.0)[0]
    assert row["frames_total"] == 2
    assert row["dropped_frames"] == 1
    assert row["mac_address"] == "aa:bb:cc:dd:ee:ff"


def test_registry_rename_persist(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db)
    client_id = "001122334455"
    registry.set_name(client_id, "rear")

    registry2 = ClientRegistry(db=db)
    hello = HelloMessage(
        client_id=bytes.fromhex(client_id),
        control_port=9011,
        sample_rate_hz=800,
        name="ignored",
        firmware_version="fw2",
    )
    registry2.update_from_hello(hello, ("10.4.0.3", 9011), now=5.0)

    row = registry2.snapshot_for_api(now=5.0)[0]
    assert row["name"] == "rear"


def test_registry_rename_normalizes_client_id(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db)
    lower_id = "001122334455"
    upper_id = lower_id.upper()

    registry.set_name(lower_id, "rear")
    registry.set_name(upper_id, "rear-updated")

    rows = registry.snapshot_for_api(now=1.0)
    assert len(rows) == 1
    assert rows[0]["id"] == lower_id
    assert rows[0]["name"] == "rear-updated"


def test_registry_snapshot_includes_persisted_offline_clients(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db)
    offline_id = "001122334455"
    registry.set_name(offline_id, "rear-right-wheel")

    registry2 = ClientRegistry(db=db)
    rows = {row["id"]: row for row in registry2.snapshot_for_api(now=10.0)}
    assert rows[offline_id]["name"] == "rear-right-wheel"
    assert rows[offline_id]["connected"] is False
    assert rows[offline_id]["mac_address"] == "00:11:22:33:44:55"


def test_registry_persist_keeps_offline_names(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db)
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

    registry2 = ClientRegistry(db=db)
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

    rows = {row["id"]: row for row in registry2.snapshot_for_api(now=4.0)}
    assert rows[offline_id]["name"] == "offline-node"


def test_registry_hello_uses_advertised_control_port(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db)
    hello = HelloMessage(
        client_id=bytes.fromhex("aabbccddeeff"),
        control_port=9010,
        sample_rate_hz=800,
        name="node",
        firmware_version="fw",
        frame_samples=200,
    )
    registry.update_from_hello(hello, ("10.4.0.2", 54321), now=1.0)

    row = registry.snapshot_for_api(now=1.0)[0]
    assert row["control_addr"] == ("10.4.0.2", 9010)
    assert row["frame_samples"] == 200


def test_registry_evicts_stale_clients(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db, stale_ttl_seconds=2.0)

    fresh = HelloMessage(
        client_id=bytes.fromhex("001122334455"),
        control_port=9010,
        sample_rate_hz=800,
        name="fresh",
        firmware_version="fw",
    )
    stale = HelloMessage(
        client_id=bytes.fromhex("aabbccddeeff"),
        control_port=9011,
        sample_rate_hz=800,
        name="stale",
        firmware_version="fw",
    )
    registry.update_from_hello(stale, ("10.4.0.2", 9000), now=1.0)
    registry.update_from_hello(fresh, ("10.4.0.3", 9001), now=3.0)

    assert set(registry.active_client_ids(now=3.1)) == {"001122334455"}
    evicted = registry.evict_stale(now=3.1)
    assert evicted == ["aabbccddeeff"]
    assert registry.get("aabbccddeeff") is None


def test_registry_staleness_uses_monotonic_clock_when_now_not_provided(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db, stale_ttl_seconds=10.0)
    now = {"wall": 1_000.0, "mono": 100.0}

    monkeypatch.setattr("vibesensor.registry.time.time", lambda: now["wall"])
    monkeypatch.setattr("vibesensor.registry.time.monotonic", lambda: now["mono"])

    hello = HelloMessage(
        client_id=bytes.fromhex("001122334455"),
        control_port=9010,
        sample_rate_hz=800,
        name="sensor",
        firmware_version="fw",
    )
    registry.update_from_hello(hello, ("10.4.0.2", 9010))

    now["wall"] = 50_000.0
    now["mono"] = 105.0

    assert registry.active_client_ids() == ["001122334455"]
    row = registry.snapshot_for_api()[0]
    assert row["connected"] is True

    now["mono"] = 120.1
    assert registry.active_client_ids() == []


def test_registry_remove_client_clears_persisted_entry(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db)
    client_id = "001122334455"
    registry.set_name(client_id, "front-left")

    assert registry.remove_client(client_id) is True
    assert registry.remove_client(client_id) is False

    registry2 = ClientRegistry(db=db)
    rows = registry2.snapshot_for_api(now=1.0)
    assert rows == []


def test_registry_detects_sensor_reset_on_large_sequence_backstep(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db)
    client_id = bytes.fromhex("aabbccddeeff")
    hello = HelloMessage(
        client_id=client_id,
        control_port=9010,
        sample_rate_hz=800,
        name="node",
        firmware_version="fw",
    )
    registry.update_from_hello(hello, ("10.4.0.2", 9010), now=1.0)
    samples = np.zeros((200, 3), dtype=np.int16)
    registry.update_from_data(
        DataMessage(
            client_id=client_id,
            seq=5000,
            t0_us=1_000_000,
            sample_count=200,
            samples=samples,
        ),
        ("10.4.0.2", 50000),
        now=2.0,
    )
    registry.update_from_data(
        DataMessage(
            client_id=client_id,
            seq=10,
            t0_us=1_250_000,
            sample_count=200,
            samples=samples,
        ),
        ("10.4.0.2", 50000),
        now=3.0,
    )
    row = registry.snapshot_for_api(now=3.0)[0]
    assert row["reset_count"] == 1
    assert row["dropped_frames"] == 0


def test_registry_exposes_timing_health_metrics(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db)
    client_id = bytes.fromhex("001122334455")
    hello = HelloMessage(
        client_id=client_id,
        control_port=9010,
        sample_rate_hz=1000,
        name="node",
        firmware_version="fw",
    )
    registry.update_from_hello(hello, ("10.4.0.2", 9010), now=1.0)
    samples = np.zeros((100, 3), dtype=np.int16)
    registry.update_from_data(
        DataMessage(client_id=client_id, seq=1, t0_us=1_000_000, sample_count=100, samples=samples),
        ("10.4.0.2", 50000),
        now=2.0,
    )
    registry.update_from_data(
        DataMessage(client_id=client_id, seq=2, t0_us=1_105_000, sample_count=100, samples=samples),
        ("10.4.0.2", 50000),
        now=3.0,
    )
    timing = registry.snapshot_for_api(now=3.0)[0]["timing_health"]
    assert timing["last_t0_us"] == 1_105_000
    assert isinstance(timing["jitter_us_ema"], float)


def test_registry_clear_name_reverts_to_default(tmp_path: Path) -> None:
    """clear_name() should remove the user-assigned name and revert to default."""
    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db)
    client_id = "001122334455"

    # Assign a user name
    registry.set_name(client_id, "Front Left Wheel")
    record = registry.get(client_id)
    assert record is not None
    assert record.name == "Front Left Wheel"

    # Clear the name
    cleared = registry.clear_name(client_id)
    assert cleared.name == f"client-{client_id[-4:]}"

    # Verify persistence: the cleared name should NOT come back after reload
    registry2 = ClientRegistry(db=db)
    rows = registry2.snapshot_for_api(now=1.0)
    names = [r["name"] for r in rows if r["id"] == client_id]
    # After clearing, the client may or may not appear in snapshot (depending on
    # whether it's currently connected). If it appears, it should have the default name.
    for name in names:
        assert name == f"client-{client_id[-4:]}"


def test_registry_clear_name_preserves_other_clients(tmp_path: Path) -> None:
    """Clearing one client's name should not affect other clients."""
    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db)

    registry.set_name("001122334455", "Front Left Wheel")
    registry.set_name("aabbccddeeff", "Rear Right Wheel")

    registry.clear_name("001122334455")

    record_other = registry.get("aabbccddeeff")
    assert record_other is not None
    assert record_other.name == "Rear Right Wheel"
