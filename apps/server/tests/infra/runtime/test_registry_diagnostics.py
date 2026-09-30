"""ClientRegistry transport-error counters, data-loss aggregation, and snapshot assembly."""

from __future__ import annotations

from test_support.runtime_lifecycle import (
    FakeClientNameStore,
    make_data_message,
    make_hello_message,
)

from vibesensor.infra.runtime.registry import ClientRegistry

_ADDR = ("10.4.0.2", 9010)


def test_note_parse_error_normalizes_client_and_invalid_queue_drops_are_ignored() -> None:
    registry = ClientRegistry()

    registry.note_parse_error("AABBCCDDEEFF")
    registry.note_server_queue_drop("AA:BB:CC:DD:EE:FF")
    registry.note_server_queue_drop(None)
    registry.note_server_queue_drop("not-a-client-id")

    record = registry.get("aabbccddeeff")
    assert record is not None
    assert record.parse_errors == 1
    assert record.server_queue_drops == 1
    assert registry.data_loss_snapshot()["tracked_clients"] == 1


def test_data_loss_snapshot_aggregates_counters_and_affected_clients() -> None:
    registry = ClientRegistry()
    alpha = make_hello_message("001122334455", name="alpha", queue_overflow_drops=3)
    registry.update_from_hello(alpha, _ADDR, now=1.0, now_mono=1.0)
    registry.update_from_data(make_data_message(alpha.client_id, 1, 1_000), _ADDR, now_mono=1.1)
    registry.update_from_data(make_data_message(alpha.client_id, 4, 2_000), _ADDR, now_mono=1.2)
    registry.note_server_queue_drop("001122334455")
    registry.note_parse_error("aabbccddeeff")
    registry.note_parse_error("aabbccddeeff")
    registry.note_parse_error("aabbccddeeff")
    registry.note_parse_error("aabbccddeeff")
    gamma = make_hello_message("112233445566", name="gamma")
    registry.update_from_hello(gamma, _ADDR, now=1.0, now_mono=1.0)

    assert registry.data_loss_snapshot() == {
        "tracked_clients": 3,
        "affected_clients": 2,
        "frames_dropped": 2,
        "queue_overflow_drops": 3,
        "server_queue_drops": 1,
        "parse_errors": 4,
    }


def test_client_snapshots_use_given_clocks_and_preserve_metrics() -> None:
    registry = ClientRegistry(live_ttl_seconds=10.0, retention_ttl_seconds=30.0)
    hello = make_hello_message("aabbccddeeff")
    registry.update_from_hello(hello, _ADDR, now=1000.0, now_mono=100.0)

    snapshots = registry.client_snapshots(
        now=1002.5,
        now_mono=102.5,
        metrics_by_client={"aabbccddeeff": {"rms": 0.5}},
    )

    assert len(snapshots) == 1
    assert snapshots[0].client_id == "aabbccddeeff"
    assert snapshots[0].connected is True
    assert snapshots[0].last_seen_age_ms == 2500
    assert snapshots[0].latest_metrics == {"rms": 0.5}


def test_client_snapshots_include_named_offline_clients() -> None:
    names = FakeClientNameStore()
    names.upsert_client_name("001122334455", "Rear Sensor")
    registry = ClientRegistry(db=names)

    snapshots = registry.client_snapshots(now=1000.0, now_mono=500.0)

    assert len(snapshots) == 1
    assert snapshots[0].client_id == "001122334455"
    assert snapshots[0].name == "Rear Sensor"
    assert snapshots[0].connected is False
