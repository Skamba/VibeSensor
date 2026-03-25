"""Tests for client_snapshot_projection — pure projection function."""

from __future__ import annotations

from unittest.mock import MagicMock

from vibesensor.infra.runtime.client_snapshot_projection import project_client_snapshots
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


class TestProjectClientSnapshots:
    def test_connected_record(self) -> None:
        """Active record with recent mono time → connected=True."""
        rec = _make_record(last_seen_mono=100.0)
        clients = {rec.client_id: rec}
        meta = _make_metadata([rec.client_id])
        snaps = project_client_snapshots(
            clients, meta, now_wall=1001.0, now_mono=105.0, live_ttl_seconds=10.0
        )
        assert len(snaps) == 1
        assert snaps[0].connected is True
        assert snaps[0].client_id == rec.client_id

    def test_disconnected_record_past_ttl(self) -> None:
        """Record whose mono time exceeds TTL → connected=False."""
        rec = _make_record(last_seen_mono=100.0)
        clients = {rec.client_id: rec}
        meta = _make_metadata([rec.client_id])
        snaps = project_client_snapshots(
            clients, meta, now_wall=1100.0, now_mono=200.0, live_ttl_seconds=10.0
        )
        assert snaps[0].connected is False

    def test_missing_record_produces_disconnected_snapshot(self) -> None:
        """Client ID known from metadata but no record → disconnected default."""
        cid = "aabbccddeeff"
        meta = _make_metadata([cid], {cid: "My Sensor"})
        snaps = project_client_snapshots(
            {}, meta, now_wall=1000.0, now_mono=500.0, live_ttl_seconds=10.0
        )
        assert len(snaps) == 1
        assert snaps[0].connected is False
        assert snaps[0].name == "My Sensor"

    def test_metrics_attached_when_provided(self) -> None:
        rec = _make_record(last_seen_mono=100.0)
        clients = {rec.client_id: rec}
        meta = _make_metadata([rec.client_id])
        metrics = {rec.client_id: {"rms": 0.5}}
        snaps = project_client_snapshots(
            clients,
            meta,
            now_wall=1001.0,
            now_mono=105.0,
            live_ttl_seconds=10.0,
            metrics_by_client=metrics,
        )
        assert snaps[0].latest_metrics == {"rms": 0.5}

    def test_age_ms_computed(self) -> None:
        rec = _make_record(last_seen=1000.0, last_seen_mono=100.0)
        clients = {rec.client_id: rec}
        meta = _make_metadata([rec.client_id])
        snaps = project_client_snapshots(
            clients, meta, now_wall=1002.5, now_mono=102.5, live_ttl_seconds=10.0
        )
        assert snaps[0].last_seen_age_ms == 2500
