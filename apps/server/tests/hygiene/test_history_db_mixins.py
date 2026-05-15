"""Guardrails for the split history persistence composition."""

from __future__ import annotations

from pathlib import Path

from vibesensor.adapters.persistence.history_db import (
    ClientNameRepository,
    RunHistoryRepository,
    SettingsSnapshotRepository,
    SQLiteHistoryEngine,
    create_history_persistence_adapters,
)
from vibesensor.adapters.persistence.history_db._queries import _HistoryDBQueryMixin
from vibesensor.adapters.persistence.history_db._run_lifecycle import _HistoryDBRunLifecycleMixin
from vibesensor.adapters.persistence.history_db._sample_io import _HistoryDBSampleIOMixin


def _public_method_names(cls: type[object]) -> set[str]:
    return {
        name
        for name in cls.__dict__
        if not name.startswith("_") and callable(getattr(cls, name, None))
    }


def test_run_history_repository_mixins_expose_disjoint_public_methods() -> None:
    mixins = (
        _HistoryDBRunLifecycleMixin,
        _HistoryDBSampleIOMixin,
        _HistoryDBQueryMixin,
    )
    owners_by_name: dict[str, list[str]] = {}

    for mixin in mixins:
        for name in _public_method_names(mixin):
            owners_by_name.setdefault(name, []).append(mixin.__name__)

    overlaps = {name: owners for name, owners in owners_by_name.items() if len(owners) > 1}
    assert overlaps == {}, f"run-history mixins must keep disjoint public APIs: {overlaps}"
    assert {
        "create_run",
        "append_samples",
        "get_run",
        "get_run_samples",
    } <= set().union(*(_public_method_names(mixin) for mixin in mixins))


def test_history_persistence_factory_returns_split_adapters(tmp_path: Path) -> None:
    adapters = create_history_persistence_adapters(tmp_path / "history.db")
    try:
        assert adapters.lifecycle is adapters.run_repository._engine
        assert adapters.lifecycle is adapters.settings_snapshot_repository._engine
        assert adapters.lifecycle is adapters.client_name_repository._engine
        assert isinstance(adapters.lifecycle, SQLiteHistoryEngine)
        assert isinstance(adapters.run_repository, RunHistoryRepository)
        assert isinstance(adapters.settings_snapshot_repository, SettingsSnapshotRepository)
        assert isinstance(adapters.client_name_repository, ClientNameRepository)
    finally:
        adapters.lifecycle.close()

    assert "_cursor_connection" not in _HistoryDBRunLifecycleMixin.__dict__
    assert "write_transaction_cursor" not in _HistoryDBSampleIOMixin.__dict__
    assert "write_transaction_cursor" not in _HistoryDBQueryMixin.__dict__
