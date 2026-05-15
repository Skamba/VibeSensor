"""Direct tests for the extracted RegistryDiagnostics helper."""

from __future__ import annotations

from threading import RLock

from vibesensor.infra.runtime.registry import ClientRecord
from vibesensor.infra.runtime.registry_diagnostics import RegistryDiagnostics


def _make_diagnostics() -> tuple[RegistryDiagnostics, dict[str, ClientRecord]]:
    lock = RLock()
    clients: dict[str, ClientRecord] = {}

    def get_or_create(client_id: str) -> ClientRecord:
        record = clients.get(client_id)
        if record is None:
            record = ClientRecord(client_id=client_id, name=f"client-{client_id[-4:]}")
            clients[client_id] = record
        return record

    return (
        RegistryDiagnostics(
            lock=lock,
            clients=clients,
            get_or_create=get_or_create,
        ),
        clients,
    )


def test_note_parse_error_normalizes_client_and_invalid_queue_drops_are_ignored() -> None:
    diagnostics, clients = _make_diagnostics()

    diagnostics.note_parse_error("AABBCCDDEEFF")
    diagnostics.note_server_queue_drop(None)
    diagnostics.note_server_queue_drop("not-a-client-id")

    record = clients["aabbccddeeff"]
    assert record.parse_errors == 1
    assert record.server_queue_drops == 0
    assert list(clients) == ["aabbccddeeff"]


def test_data_loss_snapshot_aggregates_counters_and_affected_clients() -> None:
    diagnostics, clients = _make_diagnostics()
    alpha = ClientRecord(
        client_id="001122334455",
        name="alpha",
        frames_dropped=2,
        queue_overflow_drops=3,
        server_queue_drops=1,
    )
    beta = ClientRecord(
        client_id="aabbccddeeff",
        name="beta",
        parse_errors=4,
    )
    gamma = ClientRecord(
        client_id="112233445566",
        name="gamma",
    )
    clients[alpha.client_id] = alpha
    clients[beta.client_id] = beta
    clients[gamma.client_id] = gamma

    assert diagnostics.data_loss_snapshot() == {
        "tracked_clients": 3,
        "affected_clients": 2,
        "frames_dropped": 2,
        "queue_overflow_drops": 3,
        "server_queue_drops": 1,
        "parse_errors": 4,
    }
