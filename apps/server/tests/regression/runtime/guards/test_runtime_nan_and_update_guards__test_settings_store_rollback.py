"""Runtime NaN handling and update-manager guard regressions:
NaN guards, correlation clamp, persist rollback,
firmware cache streaming, CancelledError re-raise, _normalize_lang dedup,
_weighted_percentile direct import, _dir_sha256 separators, _corr_abs_clamped,
_canonical_location edge cases, PDF peak suffix i18n."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from vibesensor.settings_store import PersistenceError, SettingsStore
from vibesensor.update.manager import UpdateManager, UpdateState


class TestUpdateManagerCancelledError:
    """Verify CancelledError is re-raised after cleanup."""

    @pytest.mark.asyncio
    async def test_cancelled_error_is_reraised(self):
        """_run_update should re-raise CancelledError."""
        mgr = UpdateManager.__new__(UpdateManager)
        mgr._status = MagicMock()
        mgr._status.phase = MagicMock()
        mgr._status.state = UpdateState.running
        mgr._status.issues = []
        mgr._status.finished_at = None
        mgr._log_lines = []
        mgr._redact_secrets = set()
        mgr._state_store = MagicMock()
        mgr._state_store.save = MagicMock()

        async def mock_inner(ssid, password):
            raise asyncio.CancelledError()

        mgr._run_update_inner = mock_inner
        mgr._add_issue = MagicMock()
        mgr._log = MagicMock()
        mgr._persist_status = MagicMock()

        async def noop_restore():
            pass

        mgr._restore_hotspot = noop_restore
        mgr._collect_runtime_details = MagicMock(return_value={})

        with pytest.raises(asyncio.CancelledError):
            await mgr._run_update("ssid", "pass")


class TestSettingsStoreRollback:
    """Verify in-memory state is restored when _persist() fails."""

    @staticmethod
    def _make_store_failing_persist() -> SettingsStore:
        """Return a SettingsStore whose _persist() will raise."""
        store = SettingsStore(db=None)
        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB fail")
        return store

    def test_add_car_rollback_on_persist_failure(self):
        store = SettingsStore(db=None)
        initial_count = len(store.get_cars()["cars"])

        # Make persist fail
        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB write fail")

        with pytest.raises(PersistenceError):
            store.add_car({"name": "New Car", "type": "suv"})

        assert len(store.get_cars()["cars"]) == initial_count

    def test_delete_car_rollback_on_persist_failure(self):
        store = SettingsStore(db=None)
        store.add_car({"name": "Car 1", "type": "sedan"})
        store.add_car({"name": "Car 2", "type": "suv"})
        cars = store.get_cars()
        car_count = len(cars["cars"])
        assert car_count >= 2
        target_id = cars["cars"][-1]["id"]

        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB fail")

        with pytest.raises(PersistenceError):
            store.delete_car(target_id)

        assert len(store.get_cars()["cars"]) == car_count

    def test_set_active_car_rollback_on_persist_failure(self):
        store = SettingsStore(db=None)
        store.add_car({"name": "Car 2", "type": "suv"})
        cars = store.get_cars()
        original_active = cars["activeCarId"]
        new_id = [c["id"] for c in cars["cars"] if c["id"] != original_active][0]

        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB fail")

        with pytest.raises(PersistenceError):
            store.set_active_car(new_id)

        assert store.get_cars()["activeCarId"] == original_active

    def test_update_car_rollback_on_persist_failure(self):
        store = SettingsStore(db=None)
        store.add_car({"name": "Original Name", "type": "sedan"})
        cars = store.get_cars()
        car_id = cars["cars"][0]["id"]
        original_name = cars["cars"][0]["name"]

        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB fail")

        with pytest.raises(PersistenceError):
            store.update_car(car_id, {"name": "New Name"})

        assert store.get_cars()["cars"][0]["name"] == original_name
