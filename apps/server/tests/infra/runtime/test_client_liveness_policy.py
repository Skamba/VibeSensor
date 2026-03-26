"""Tests for the extracted ClientLivenessPolicy helper."""

from __future__ import annotations

from vibesensor.infra.runtime.client_liveness_policy import ClientLivenessPolicy
from vibesensor.infra.runtime.registry import ClientRecord


def _make_record(
    client_id: str,
    *,
    last_seen_mono: float,
) -> ClientRecord:
    return ClientRecord(
        client_id=client_id,
        name=f"Sensor-{client_id[:4]}",
        last_seen_mono=last_seen_mono,
    )


def test_policy_clamps_retention_ttl_to_live_ttl() -> None:
    policy = ClientLivenessPolicy(live_ttl_seconds=5.0, retention_ttl_seconds=1.0)

    assert policy.live_ttl_seconds == 5.0
    assert policy.retention_ttl_seconds == 5.0


def test_is_live_uses_live_ttl_boundary() -> None:
    policy = ClientLivenessPolicy(live_ttl_seconds=10.0, retention_ttl_seconds=30.0)
    record = _make_record("001122334455", last_seen_mono=100.0)

    assert policy.is_live(record, 110.0) is True
    assert policy.is_live(record, 110.1) is False


def test_is_retained_uses_retention_ttl_boundary() -> None:
    policy = ClientLivenessPolicy(live_ttl_seconds=10.0, retention_ttl_seconds=30.0)
    record = _make_record("001122334455", last_seen_mono=100.0)

    assert policy.is_retained(record, 130.0) is True
    assert policy.is_retained(record, 130.1) is False


def test_active_client_ids_returns_live_records_in_mapping_order() -> None:
    policy = ClientLivenessPolicy(live_ttl_seconds=10.0, retention_ttl_seconds=30.0)
    clients = {
        "001122334455": _make_record("001122334455", last_seen_mono=100.0),
        "aabbccddeeff": _make_record("aabbccddeeff", last_seen_mono=90.0),
        "112233445566": _make_record("112233445566", last_seen_mono=104.0),
    }

    assert policy.active_client_ids(clients, 105.0) == ["001122334455", "112233445566"]


def test_stale_client_ids_ignores_never_seen_records_and_preserves_order() -> None:
    policy = ClientLivenessPolicy(live_ttl_seconds=10.0, retention_ttl_seconds=30.0)
    clients = {
        "001122334455": _make_record("001122334455", last_seen_mono=60.0),
        "aabbccddeeff": _make_record("aabbccddeeff", last_seen_mono=0.0),
        "112233445566": _make_record("112233445566", last_seen_mono=90.0),
    }

    assert policy.stale_client_ids(clients, 100.0) == ["001122334455"]
