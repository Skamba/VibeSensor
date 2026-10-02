"""Tests for the pure registry-to-ClientSnapshot projection."""

from __future__ import annotations

from unittest.mock import MagicMock

from vibesensor.ingest.registry import (
    ClientLivenessPolicy,
    ClientRecord,
    project_client_snapshots,
)


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


_POLICY = ClientLivenessPolicy(live_ttl_seconds=10.0, retention_ttl_seconds=30.0)


class TestProjectClientSnapshots:
    """Cover connected/offline projection, ages, and optional metrics attachment."""

    def test_connected_record_projects_age_and_metrics(self) -> None:
        """Active record within the live TTL → connected, with age and optional metrics."""
        rec = _make_record(last_seen=1000.0, last_seen_mono=100.0)
        snaps = project_client_snapshots(
            {rec.client_id: rec},
            _make_metadata([rec.client_id]),
            now_wall=1002.5,
            now_mono=102.5,
            policy=_POLICY,
            metrics_by_client={rec.client_id: {"rms": 0.5}},
        )
        assert len(snaps) == 1
        assert snaps[0].client_id == rec.client_id
        assert snaps[0].connected is True
        assert snaps[0].last_seen_age_ms == 2500
        assert snaps[0].latest_metrics == {"rms": 0.5}

    def test_disconnected_record_past_ttl(self) -> None:
        """Record whose mono time exceeds TTL → connected=False."""
        rec = _make_record(last_seen_mono=100.0)
        clients = {rec.client_id: rec}
        meta = _make_metadata([rec.client_id])
        snaps = project_client_snapshots(
            clients,
            meta,
            now_wall=1100.0,
            now_mono=200.0,
            policy=_POLICY,
        )
        assert snaps[0].connected is False

    def test_missing_record_produces_disconnected_snapshot(self) -> None:
        """Client ID known from metadata but no record → disconnected default."""
        cid = "aabbccddeeff"
        meta = _make_metadata([cid], {cid: "My Sensor"})
        snaps = project_client_snapshots(
            {},
            meta,
            now_wall=1000.0,
            now_mono=500.0,
            policy=_POLICY,
        )
        assert len(snaps) == 1
        assert snaps[0].connected is False
        assert snaps[0].name == "My Sensor"
