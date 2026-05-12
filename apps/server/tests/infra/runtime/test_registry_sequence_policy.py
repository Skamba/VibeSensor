"""Registry sequence/deduplication behavior contracts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from test_support.runtime_lifecycle import (
    build_registry_with_hello as _make_registry_with_hello,
)
from test_support.runtime_lifecycle import make_data_message as _data_msg

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.adapters.udp.protocol import DataMessage, HelloMessage
from vibesensor.infra.runtime.registry import ClientRegistry
from vibesensor.shared.boundaries.clients import snapshot_for_api


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
