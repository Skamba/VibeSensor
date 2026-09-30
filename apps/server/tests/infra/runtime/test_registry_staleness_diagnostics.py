"""Registry staleness and diagnostics contracts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from test_support.runtime_lifecycle import build_history_db as _build_history_db
from test_support.runtime_lifecycle import build_registry as _build_registry
from test_support.runtime_lifecycle import make_hello_message as _make_hello_message

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.adapters.udp.protocol import DataMessage, HelloMessage
from vibesensor.infra.runtime.registry import ClientRegistry
from vibesensor.shared.boundaries.clients import snapshot_for_api


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
    assert record.timing_jitter_us_ema == 1_000.0
    assert record.timing_drift_us_total == 5_000.0
