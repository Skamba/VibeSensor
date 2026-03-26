"""Direct tests for the extracted ClientSnapshotAssembler helper."""

from __future__ import annotations

from threading import RLock
from unittest.mock import MagicMock

from vibesensor.infra.runtime.client_liveness_policy import ClientLivenessPolicy
from vibesensor.infra.runtime.client_snapshot_assembler import ClientSnapshotAssembler
from vibesensor.infra.runtime.registry import ClientRecord


def _make_record(
    client_id: str = "aabbccddeeff",
    name: str = "Sensor-1",
    last_seen: float = 1000.0,
    last_seen_mono: float = 500.0,
    **kwargs,
) -> ClientRecord:
    return ClientRecord(
        client_id=client_id,
        name=name,
        last_seen=last_seen,
        last_seen_mono=last_seen_mono,
        **kwargs,
    )


def _make_metadata(known_ids: list[str], names: dict[str, str] | None = None) -> MagicMock:
    names = names or {}
    meta = MagicMock()
    meta.known_client_ids.return_value = known_ids
    meta.default_name_for.side_effect = lambda cid: names.get(cid, f"Sensor-{cid[:4]}")
    return meta


def test_assembler_uses_time_resolvers_and_preserves_metrics() -> None:
    record = _make_record(last_seen=1000.0, last_seen_mono=100.0)
    clients = {record.client_id: record}
    metadata = _make_metadata([record.client_id])
    policy = ClientLivenessPolicy(live_ttl_seconds=10.0, retention_ttl_seconds=30.0)
    wall_calls: list[float | None] = []
    mono_calls: list[float | None] = []

    assembler = ClientSnapshotAssembler(
        lock=RLock(),
        clients=clients,
        metadata=metadata,
        policy=policy,
        resolve_now_wall=lambda now: wall_calls.append(now) or 1002.5,
        resolve_now_mono=lambda now: mono_calls.append(now) or 102.5,
    )

    snapshots = assembler.client_snapshots(metrics_by_client={record.client_id: {"rms": 0.5}})

    assert wall_calls == [None]
    assert mono_calls == [None]
    assert len(snapshots) == 1
    assert snapshots[0].client_id == record.client_id
    assert snapshots[0].connected is True
    assert snapshots[0].last_seen_age_ms == 2500
    assert snapshots[0].latest_metrics == {"rms": 0.5}


def test_assembler_includes_metadata_only_offline_clients() -> None:
    metadata = _make_metadata(["001122334455"], {"001122334455": "Rear Sensor"})
    assembler = ClientSnapshotAssembler(
        lock=RLock(),
        clients={},
        metadata=metadata,
        policy=ClientLivenessPolicy(live_ttl_seconds=10.0, retention_ttl_seconds=30.0),
        resolve_now_wall=lambda now: 1000.0,
        resolve_now_mono=lambda now: 500.0,
    )

    snapshots = assembler.client_snapshots(now=1000.0, now_mono=500.0)

    assert len(snapshots) == 1
    assert snapshots[0].client_id == "001122334455"
    assert snapshots[0].name == "Rear Sensor"
    assert snapshots[0].connected is False
