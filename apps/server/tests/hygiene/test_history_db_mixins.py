"""Guardrails for the intentional ``HistoryDB`` mixin composition."""

from __future__ import annotations

from vibesensor.adapters.persistence.history_db import HistoryDB
from vibesensor.adapters.persistence.history_db._queries import _HistoryDBQueryMixin
from vibesensor.adapters.persistence.history_db._run_lifecycle import _HistoryDBRunLifecycleMixin
from vibesensor.adapters.persistence.history_db._sample_io import _HistoryDBSampleIOMixin


def _public_method_names(cls: type[object]) -> set[str]:
    return {
        name
        for name in cls.__dict__
        if not name.startswith("_") and callable(getattr(cls, name, None))
    }


def test_history_db_mixins_expose_disjoint_public_methods() -> None:
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
    assert overlaps == {}, f"HistoryDB mixins must keep disjoint public APIs: {overlaps}"


def test_history_db_wrapper_owns_shared_cursor_contract() -> None:
    history_db_members = set(HistoryDB.__dict__)

    assert {"_cursor", "_cursor_connection"} <= history_db_members
    assert "write_transaction_cursor" in history_db_members

    assert "_cursor_connection" not in _HistoryDBRunLifecycleMixin.__dict__
    assert "write_transaction_cursor" not in _HistoryDBSampleIOMixin.__dict__
    assert "write_transaction_cursor" not in _HistoryDBQueryMixin.__dict__

    for mixin in (_HistoryDBSampleIOMixin, _HistoryDBQueryMixin):
        assert "_cursor_connection" not in mixin.__dict__, (
            "sample/query mixins must rely on the wrapper-owned cursor-selection logic"
        )
