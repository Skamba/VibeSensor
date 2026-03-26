"""Tests for the standalone settings update-with-rollback transaction helper."""

from __future__ import annotations

from threading import RLock

import pytest

from vibesensor.infra.config.settings_transaction import update_with_rollback
from vibesensor.shared.exceptions import PersistenceError


def _make_state() -> dict[str, int]:
    return {"value": 1}


def _apply_state_value(state: dict[str, int], value: int):
    def _apply(_prev: dict[str, int]) -> bool:
        state["value"] = value
        return True

    return _apply


class TestUpdateWithRollback:
    """Exercise the generic snapshot→apply→persist→audit→restore flow."""

    def test_successful_update(self) -> None:
        state = _make_state()
        audit_calls: list[dict[str, int]] = []

        got = update_with_rollback(
            lock=RLock(),
            persist=lambda: None,
            snapshot=lambda: dict(state),
            apply=_apply_state_value(state, 10),
            restore=lambda prev: state.update(prev),
            audit_log=lambda prev: audit_calls.append(prev),
            result=lambda: state["value"],
        )

        assert got == 10
        assert audit_calls == [{"value": 1}]

    def test_noop_skips_persist(self) -> None:
        persist_calls: list[bool] = []

        got = update_with_rollback(
            lock=RLock(),
            persist=lambda: persist_calls.append(True),
            snapshot=lambda: {},
            apply=lambda _prev: False,
            restore=lambda _prev: None,
            result=lambda: "unchanged",
        )

        assert got == "unchanged"
        assert persist_calls == []

    def test_rollback_on_persistence_error(self) -> None:
        state = _make_state()

        def bad_persist() -> None:
            raise PersistenceError("disk full")

        with pytest.raises(PersistenceError, match="disk full"):
            update_with_rollback(
                lock=RLock(),
                persist=bad_persist,
                snapshot=lambda: dict(state),
                apply=_apply_state_value(state, 99),
                restore=lambda prev: state.update(prev),
                result=lambda: state["value"],
            )

        assert state == {"value": 1}, "state must be restored after failure"

    def test_after_persist_called(self) -> None:
        side_effects: list[str] = []

        update_with_rollback(
            lock=RLock(),
            persist=lambda: None,
            snapshot=lambda: {},
            apply=lambda _prev: True,
            restore=lambda _prev: None,
            after_persist=lambda: side_effects.append("done"),
            result=lambda: None,
        )

        assert side_effects == ["done"]

    def test_after_persist_not_called_on_failure(self) -> None:
        side_effects: list[str] = []

        with pytest.raises(PersistenceError):
            update_with_rollback(
                lock=RLock(),
                persist=_raise_persistence_error,
                snapshot=lambda: {},
                apply=lambda _prev: True,
                restore=lambda _prev: None,
                after_persist=lambda: side_effects.append("should not happen"),
                result=lambda: None,
            )

        assert side_effects == []

    def test_audit_log_not_called_on_failure(self) -> None:
        audit_calls: list[object] = []

        with pytest.raises(PersistenceError):
            update_with_rollback(
                lock=RLock(),
                persist=_raise_persistence_error,
                snapshot=lambda: "snap",
                apply=lambda _prev: True,
                restore=lambda _prev: None,
                audit_log=lambda prev: audit_calls.append(prev),
                result=lambda: None,
            )

        assert audit_calls == []


def _raise_persistence_error() -> None:
    raise PersistenceError("boom")
