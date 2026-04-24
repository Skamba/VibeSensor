"""Cover registry protocol updates, persistence, deduplication, and snapshot behavior."""

from __future__ import annotations

from pathlib import Path

import numpy as np
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
    build_registry_with_hello as _make_registry_with_hello,
)
from test_support.runtime_lifecycle import (
    make_data_message as _data_msg,
)
from test_support.runtime_lifecycle import (
    make_hello_message as _make_hello_message,
)

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.adapters.udp.protocol import DataMessage, HelloMessage
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


def test_registry_sequence_gap(tmp_path: Path) -> None:
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

    samples = np.zeros((200, 3), dtype=np.int16)
    msg0 = DataMessage(client_id=client_id, seq=0, t0_us=10, sample_count=200, samples=samples)
    msg1 = DataMessage(client_id=client_id, seq=2, t0_us=20, sample_count=200, samples=samples)
    registry.update_from_data(msg0, ("10.4.0.2", 50000), now=2.0)
    registry.update_from_data(msg1, ("10.4.0.2", 50000), now=3.0)

    row = snapshot_for_api(registry, now=3.0)[0]
    assert row["frames_total"] == 2
    assert row["dropped_frames"] == 1
    assert row["mac_address"] == "aa:bb:cc:dd:ee:ff"


def test_registry_rejects_far_behind_duplicate_without_clearing_dedup(tmp_path: Path) -> None:
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

    samples = np.zeros((200, 3), dtype=np.int16)
    registry.update_from_data(
        DataMessage(client_id=client_id, seq=1, t0_us=1_000_000, sample_count=200, samples=samples),
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

    result = registry.update_from_data(
        DataMessage(client_id=client_id, seq=1, t0_us=1_000_000, sample_count=200, samples=samples),
        ("10.4.0.2", 50000),
        now=4.0,
    )

    record = registry.get(client_id.hex())
    assert record is not None
    assert result.is_duplicate is True
    assert result.reset_detected is False
    assert record.frames_total == 2
    assert record.duplicates_received == 1
    assert record.last_t0_us == 1_250_000


def test_registry_rename_persist(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    registry = ClientRegistry(db=db.client_name_repository)
    client_id = "001122334455"
    registry.set_name(client_id, "rear")

    registry2 = ClientRegistry(db=db.client_name_repository)
    hello = HelloMessage(
        client_id=bytes.fromhex(client_id),
        control_port=9011,
        sample_rate_hz=800,
        name="ignored",
        firmware_version="fw2",
    )
    registry2.update_from_hello(hello, ("10.4.0.3", 9011), now=5.0)

    row = snapshot_for_api(registry2, now=5.0)[0]
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


def test_registry_snapshot_includes_persisted_offline_clients(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    registry = ClientRegistry(db=db.client_name_repository)
    offline_id = "001122334455"
    registry.set_name(offline_id, "rear-right-wheel")

    registry2 = ClientRegistry(db=db.client_name_repository)
    rows = {row["id"]: row for row in snapshot_for_api(registry2, now=10.0)}
    assert rows[offline_id]["name"] == "rear-right-wheel"
    assert rows[offline_id]["connected"] is False
    assert rows[offline_id]["mac_address"] == "00:11:22:33:44:55"


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


def test_registry_evicts_stale_clients(tmp_path: Path) -> None:
    db = _build_history_db(tmp_path)
    registry = _build_registry(db=db, live_ttl_seconds=2.0, retention_ttl_seconds=2.0)

    fresh = _make_hello_message("001122334455", control_port=9010, name="fresh")
    stale = _make_hello_message(control_port=9011, name="stale")
    registry.update_from_hello(stale, ("10.4.0.2", 9000), now=1.0, now_mono=1.0)
    registry.update_from_hello(fresh, ("10.4.0.3", 9001), now=3.0, now_mono=3.0)

    assert set(registry.active_client_ids(now_mono=3.1)) == {"001122334455"}
    evicted = registry.evict_stale(now_mono=3.1)
    assert evicted == ["aabbccddeeff"]
    assert registry.get("aabbccddeeff") is None


def test_registry_staleness_uses_monotonic_clock_when_now_not_provided(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db = _build_history_db(tmp_path)
    registry = _build_registry(db=db, live_ttl_seconds=10.0, retention_ttl_seconds=30.0)
    now = {"wall": 1_000.0, "mono": 100.0}

    monkeypatch.setattr("vibesensor.infra.runtime.registry.time.time", lambda: now["wall"])
    monkeypatch.setattr("vibesensor.infra.runtime.registry.time.monotonic", lambda: now["mono"])

    hello = _make_hello_message("001122334455", name="sensor")
    registry.update_from_hello(hello, ("10.4.0.2", 9010))

    now["wall"] = 50_000.0
    now["mono"] = 105.0

    assert registry.active_client_ids() == ["001122334455"]
    row = snapshot_for_api(
        registry,
    )[0]
    assert row["connected"] is True

    now["mono"] = 120.1
    assert registry.active_client_ids() == []
    stale_row = snapshot_for_api(registry)[0]
    assert stale_row["connected"] is False
    assert stale_row["last_seen_age_ms"] is not None


def test_registry_retains_stale_client_until_retention_ttl(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    registry = ClientRegistry(
        db=db.client_name_repository,
        live_ttl_seconds=5.0,
        retention_ttl_seconds=30.0,
    )
    hello = HelloMessage(
        client_id=bytes.fromhex("001122334455"),
        control_port=9010,
        sample_rate_hz=800,
        name="sensor",
        firmware_version="fw",
    )
    registry.update_from_hello(hello, ("10.4.0.2", 9010), now=1.0, now_mono=1.0)

    assert registry.active_client_ids(now_mono=4.0) == ["001122334455"]
    stale_row = snapshot_for_api(registry, now=9.0, now_mono=9.0)[0]
    assert stale_row["connected"] is False
    assert stale_row["last_seen_age_ms"] == 8000
    assert registry.active_client_ids(now_mono=9.0) == []
    assert registry.evict_stale(now_mono=9.0) == []

    assert registry.evict_stale(now_mono=32.0) == ["001122334455"]
    assert registry.get("001122334455") is None


def test_registry_data_loss_snapshot_preserves_public_counter_shape(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    registry = ClientRegistry(db=db.client_name_repository)
    client_id = bytes.fromhex("001122334455")
    hello = HelloMessage(
        client_id=client_id,
        control_port=9010,
        sample_rate_hz=800,
        name="sensor",
        firmware_version="fw",
        queue_overflow_drops=2,
    )
    registry.update_from_hello(hello, ("10.4.0.2", 9010), now=1.0)

    samples = np.zeros((200, 3), dtype=np.int16)
    registry.update_from_data(
        DataMessage(client_id=client_id, seq=0, t0_us=10, sample_count=200, samples=samples),
        ("10.4.0.2", 50000),
        now=2.0,
    )
    registry.update_from_data(
        DataMessage(client_id=client_id, seq=2, t0_us=20, sample_count=200, samples=samples),
        ("10.4.0.2", 50000),
        now=3.0,
    )
    registry.note_parse_error("001122334455")
    registry.note_server_queue_drop("001122334455")

    assert registry.data_loss_snapshot() == {
        "tracked_clients": 1,
        "affected_clients": 1,
        "frames_dropped": 1,
        "queue_overflow_drops": 2,
        "server_queue_drops": 1,
        "parse_errors": 1,
    }


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


def test_registry_detects_sensor_reset_on_large_sequence_backstep(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    registry = ClientRegistry(db=db.client_name_repository)
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
    row = snapshot_for_api(registry, now=3.0)[0]
    assert row["reset_count"] == 1
    assert row["dropped_frames"] == 0


def test_registry_exposes_timing_health_metrics(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    registry = ClientRegistry(db=db.client_name_repository)
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
    record = registry.get(client_id.hex())
    assert record is not None
    assert record.last_t0_us == 1_105_000
    assert isinstance(record.timing_jitter_us_ema, float)


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

    # Verify persistence: the cleared name should NOT come back after reload
    registry2 = ClientRegistry(db=db.client_name_repository)
    rows = snapshot_for_api(registry2, now=1.0)
    names = [r["name"] for r in rows if r["id"] == client_id]
    # After clearing, the client may or may not appear in snapshot (depending on
    # whether it's currently connected). If it appears, it should have the default name.
    for name in names:
        assert name == f"client-{client_id[-4:]}"


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


def test_duplicate_seq_is_detected(tmp_path: Path) -> None:
    """Sending the same seq twice should flag the second as a duplicate."""
    registry, client_id = _make_registry_with_hello(tmp_path)
    msg = _data_msg(client_id, 0, 10, sample_count=200)

    r1 = registry.update_from_data(msg, ("10.4.0.2", 50000), now=2.0)
    assert r1.is_duplicate is False

    r2 = registry.update_from_data(msg, ("10.4.0.2", 50000), now=3.0)
    assert r2.is_duplicate is True

    row = snapshot_for_api(registry, now=3.0)[0]
    assert row["frames_total"] == 1
    assert registry.get(client_id.hex()).duplicates_received == 1


def test_duplicate_does_not_inflate_frames_total(tmp_path: Path) -> None:
    """Duplicate retransmits must not inflate the frames_total counter."""
    registry, client_id = _make_registry_with_hello(tmp_path)

    for seq in range(5):
        msg = _data_msg(client_id, seq, seq * 10000)
        registry.update_from_data(msg, ("10.4.0.2", 50000), now=2.0 + seq)

    # Retransmit seq=2 and seq=3
    for seq in (2, 3):
        msg = _data_msg(client_id, seq, seq * 10000)
        registry.update_from_data(msg, ("10.4.0.2", 50000), now=10.0 + seq)

    row = snapshot_for_api(registry, now=15.0)[0]
    assert row["frames_total"] == 5
    assert registry.get(client_id.hex()).duplicates_received == 2
    assert row["dropped_frames"] == 0


def test_out_of_order_packet_is_marked_late_without_rewinding_live_state(
    tmp_path: Path,
) -> None:
    """A late non-duplicate frame should not mutate the live sequence state."""
    registry, client_id = _make_registry_with_hello(tmp_path)

    # Send seq 0, 2 (skip 1), then 1 arrives late
    for seq in (0, 2):
        msg = _data_msg(client_id, seq, seq * 10000)
        registry.update_from_data(msg, ("10.4.0.2", 50000), now=2.0 + seq)

    msg1 = _data_msg(client_id, 1, 10000)
    r = registry.update_from_data(msg1, ("10.4.0.2", 50000), now=5.0)
    assert r.is_duplicate is False
    assert r.is_late is True

    row = snapshot_for_api(registry, now=5.0)[0]
    assert row["frames_total"] == 2
    assert row["dropped_frames"] == 1
    assert registry.get(client_id.hex()).duplicates_received == 0
    assert registry.get(client_id.hex()).last_seq == 2
    assert registry.get(client_id.hex()).last_t0_us == 20_000


def test_reset_clears_seen_seqs(tmp_path: Path) -> None:
    """After a sensor reset, the same low seq numbers should be accepted again."""
    registry, client_id = _make_registry_with_hello(tmp_path)

    # First session: seq 5000
    msg_high = _data_msg(client_id, 5000, 1_000_000)
    registry.update_from_data(msg_high, ("10.4.0.2", 50000), now=2.0)

    # Reset: seq drops to 0
    msg_low = _data_msg(client_id, 0, 2_000_000)
    r = registry.update_from_data(msg_low, ("10.4.0.2", 50000), now=3.0)
    assert r.reset_detected is True
    assert r.is_duplicate is False

    # seq 1 after reset should also be accepted
    msg_1 = _data_msg(client_id, 1, 2_010_000)
    r2 = registry.update_from_data(msg_1, ("10.4.0.2", 50000), now=4.0)
    assert r2.is_duplicate is False

    row = snapshot_for_api(registry, now=4.0)[0]
    assert row["frames_total"] == 3
    assert registry.get(client_id.hex()).duplicates_received == 0


def test_short_session_restart_beyond_dedup_window_not_flagged_as_duplicate(
    tmp_path: Path,
) -> None:
    """Short-session restart must not depend on the dedup window retaining seq=0.

    Reproduces the E2E failure where the simulator runs twice with the same
    client IDs but fewer than 1000 frames (below the hard-reset threshold).
    """
    registry, client_id = _make_registry_with_hello(tmp_path)

    # First session: seq 0..199 (below the hard-reset threshold, but well past
    # the 128-entry dedup window so the second session cannot rely on seen-seq
    # retention for restart handling).
    for seq in range(200):
        msg = _data_msg(client_id, seq, seq * 10000)
        registry.update_from_data(msg, ("10.4.0.2", 50000), now=2.0 + seq * 0.01)

    row = snapshot_for_api(registry, now=3.0)[0]
    assert row["frames_total"] == 200
    assert registry.get(client_id.hex()).duplicates_received == 0

    # Second session: simulator restarts, seq goes back to 0
    for seq in range(50):
        msg = _data_msg(client_id, seq, 3_000_000 + seq * 10000)
        r = registry.update_from_data(msg, ("10.4.0.2", 50000), now=5.0 + seq * 0.01)
        assert r.is_duplicate is False, f"seq={seq} wrongly flagged as duplicate"

    row2 = snapshot_for_api(registry, now=6.0)[0]
    assert row2["frames_total"] == 250
    assert registry.get(client_id.hex()).duplicates_received == 0


def test_ultra_short_session_restart_not_flagged_as_duplicate(tmp_path: Path) -> None:
    """A four-frame restart must not drop the next seq=0..3 window."""
    registry, client_id = _make_registry_with_hello(tmp_path)

    for seq in range(4):
        msg = _data_msg(client_id, seq, seq * 10_000)
        registry.update_from_data(msg, ("10.4.0.2", 50000), now=2.0 + seq * 0.01)

    row = snapshot_for_api(registry, now=3.0)[0]
    assert row["frames_total"] == 4
    assert registry.get(client_id.hex()).duplicates_received == 0

    for seq in range(4):
        msg = _data_msg(client_id, seq, 100_000 + seq * 10_000)
        r = registry.update_from_data(msg, ("10.4.0.2", 50000), now=5.0 + seq * 0.01)
        assert r.is_duplicate is False, f"seq={seq} wrongly flagged as duplicate"

    row2 = snapshot_for_api(registry, now=6.0)[0]
    assert row2["frames_total"] == 8
    assert registry.get(client_id.hex()).duplicates_received == 0
