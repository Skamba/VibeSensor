"""Cover runtime client-name persistence, clearing, and advertised-name application."""

from __future__ import annotations

from pathlib import Path
from threading import RLock

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.domain import normalize_sensor_id
from vibesensor.infra.runtime.client_metadata import ClientMetadataManager
from vibesensor.infra.runtime.registry import ClientRecord


def _build_manager(db_path: Path) -> tuple[ClientMetadataManager, dict[str, ClientRecord]]:
    records: dict[str, ClientRecord] = {}

    def _get_or_create(client_id: str) -> ClientRecord:
        normalized = normalize_sensor_id(client_id)
        record = records.get(normalized)
        if record is None:
            record = ClientRecord(
                client_id=normalized,
                name=f"client-{normalized[-4:]}",
            )
            records[normalized] = record
        return record

    db = create_history_persistence_adapters(db_path)
    manager = ClientMetadataManager(
        lock=RLock(),
        get_or_create=_get_or_create,
        list_client_names=db.client_name_repository.list_client_names,
        persist_client_name=db.client_name_repository.upsert_client_name,
        delete_client_name=db.client_name_repository.delete_client_name,
    )
    return manager, records


def test_set_name_persists_and_updates_record(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    manager, _records = _build_manager(db_path)

    record = manager.set_name("001122334455", "Front Left Wheel")

    assert record.client_id == "001122334455"
    assert record.name == "Front Left Wheel"

    reloaded, _ = _build_manager(db_path)
    assert reloaded.default_name_for("001122334455") == "Front Left Wheel"


def test_clear_name_restores_default_and_deletes_persisted_entry(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    manager, _records = _build_manager(db_path)
    manager.set_name("001122334455", "Front Left Wheel")

    cleared = manager.clear_name("001122334455")

    assert cleared.name == "client-4455"

    reloaded, _ = _build_manager(db_path)
    assert reloaded.default_name_for("001122334455") == "client-4455"


def test_apply_advertised_name_respects_user_override(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    manager, records = _build_manager(db_path)
    record = manager.set_name("001122334455", "Front Left Wheel")

    manager.apply_advertised_name(record, "hello-advertised")
    assert record.name == "Front Left Wheel"

    advertised = records.setdefault(
        "aabbccddeeff",
        ClientRecord(client_id="aabbccddeeff", name="client-eeff"),
    )
    manager.apply_advertised_name(advertised, "Rear Sensor")
    assert advertised.name == "Rear Sensor"
