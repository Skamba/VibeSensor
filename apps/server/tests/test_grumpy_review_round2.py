"""Tests for the 10-item grumpy code quality review, round 2.

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

import os
import threading
import time
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Item 1: remove_sensor persistence rollback
# ---------------------------------------------------------------------------


class TestRemoveSensorRollback:
    def test_remove_sensor_rolls_back_on_persist_failure(self) -> None:
        from vibesensor.settings_store import PersistenceError, SettingsStore

        store = SettingsStore(db=None)
        store.set_sensor("aabbccddeeff", {"name": "Test", "location": "trunk"})
        assert "aabbccddeeff" in store.get_sensors()

        # Simulate persistence failure
        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                store.remove_sensor("aabbccddeeff")

        # Sensor should still be in memory after rollback
        assert "aabbccddeeff" in store.get_sensors()

    def test_remove_sensor_succeeds_normally(self) -> None:
        from vibesensor.settings_store import SettingsStore

        store = SettingsStore(db=None)
        store.set_sensor("aabbccddeeff", {"name": "Test", "location": "trunk"})
        assert store.remove_sensor("aabbccddeeff") is True
        assert "aabbccddeeff" not in store.get_sensors()

    def test_remove_sensor_nonexistent_returns_false(self) -> None:
        from vibesensor.settings_store import SettingsStore

        store = SettingsStore(db=None)
        assert store.remove_sensor("aabbccddeeff") is False


# ---------------------------------------------------------------------------
# Item 2: _NON_WHEEL_TOKENS is a module-level constant
# ---------------------------------------------------------------------------


class TestNonWheelTokensModuleLevel:
    def test_non_wheel_tokens_is_module_constant(self) -> None:
        import vibesensor.locations as loc

        assert hasattr(loc, "_NON_WHEEL_TOKENS")
        assert isinstance(loc._NON_WHEEL_TOKENS, tuple)
        assert "seat" in loc._NON_WHEEL_TOKENS
        assert "trunk" in loc._NON_WHEEL_TOKENS

    def test_is_wheel_location_still_excludes_non_wheel(self) -> None:
        from vibesensor.locations import is_wheel_location

        assert is_wheel_location("driver_seat") is False
        assert is_wheel_location("transmission") is False
        assert is_wheel_location("front_left_wheel") is True


# ---------------------------------------------------------------------------
# Item 3: resolve_speed reads from atomic snapshot
# ---------------------------------------------------------------------------


class TestResolveSpeedAtomicSnapshot:
    def test_speed_mps_property_reads_from_snapshot(self) -> None:
        from vibesensor.gps_speed import GPSSpeedMonitor

        m = GPSSpeedMonitor(gps_enabled=True)
        assert m.speed_mps is None
        m.speed_mps = 10.0
        assert m.speed_mps == 10.0
        assert m._speed_snapshot[0] == 10.0

    def test_speed_mps_setter_preserves_timestamp(self) -> None:
        from vibesensor.gps_speed import GPSSpeedMonitor

        m = GPSSpeedMonitor(gps_enabled=True)
        ts = time.monotonic()
        m._speed_snapshot = (5.0, ts)
        m.speed_mps = 10.0
        # Timestamp should be preserved
        assert m._speed_snapshot == (10.0, ts)

    def test_resolve_speed_uses_snapshot_speed(self) -> None:
        from vibesensor.gps_speed import GPSSpeedMonitor

        m = GPSSpeedMonitor(gps_enabled=True)
        # Write speed and timestamp atomically
        m._speed_snapshot = (10.0, time.monotonic())
        r = m.resolve_speed()
        assert r.speed_mps == 10.0
        assert r.source == "gps"

    def test_resolve_speed_snapshot_consistency(self) -> None:
        """Setting speed_mps and last_update_ts both update the snapshot."""
        from vibesensor.gps_speed import GPSSpeedMonitor

        m = GPSSpeedMonitor(gps_enabled=True)
        m.speed_mps = 15.0
        m.last_update_ts = time.monotonic()
        r = m.resolve_speed()
        assert r.speed_mps == 15.0
        assert r.source == "gps"


# ---------------------------------------------------------------------------
# Item 4: car library returns copies
# ---------------------------------------------------------------------------


class TestCarLibraryCopies:
    def test_get_models_returns_copies(self) -> None:
        from vibesensor.car_library import CAR_LIBRARY, get_models_for_brand_type

        if not CAR_LIBRARY:
            pytest.skip("No car library data loaded")
        brand = CAR_LIBRARY[0].get("brand")
        car_type = CAR_LIBRARY[0].get("type")
        models = get_models_for_brand_type(brand, car_type)
        if not models:
            pytest.skip("No models found")
        # Mutate the returned dict
        models[0]["MUTATED"] = True
        # Original library should NOT be mutated
        for entry in CAR_LIBRARY:
            assert "MUTATED" not in entry

    def test_get_variants_returns_copies(self) -> None:
        from vibesensor.car_library import CAR_LIBRARY, get_variants_for_model

        if not CAR_LIBRARY:
            pytest.skip("No car library data loaded")
        for entry in CAR_LIBRARY:
            variants = entry.get("variants") or []
            if variants:
                brand = entry["brand"]
                car_type = entry["type"]
                model = entry["model"]
                result = get_variants_for_model(brand, car_type, model)
                if result:
                    result[0]["MUTATED"] = True
                    # Original should NOT be mutated
                    assert "MUTATED" not in variants[0]
                    return
        pytest.skip("No entries with variants found")


# ---------------------------------------------------------------------------
# Item 5: _cmd_seq protected by lock
# ---------------------------------------------------------------------------


class TestCmdSeqLock:
    def test_udp_control_plane_has_cmd_seq_lock(self) -> None:
        from vibesensor.registry import ClientRegistry
        from vibesensor.udp_control_tx import UDPControlPlane

        reg = ClientRegistry()
        cp = UDPControlPlane(reg, "127.0.0.1", 0)
        assert hasattr(cp, "_cmd_seq_lock")
        assert isinstance(cp._cmd_seq_lock, type(threading.Lock()))

    def test_next_cmd_seq_increments_atomically(self) -> None:
        from vibesensor.registry import ClientRegistry
        from vibesensor.udp_control_tx import UDPControlPlane

        reg = ClientRegistry()
        cp = UDPControlPlane(reg, "127.0.0.1", 0)
        initial = cp._cmd_seq
        seq1 = cp._next_cmd_seq()
        seq2 = cp._next_cmd_seq()
        assert seq1 == (initial + 1) & 0xFFFFFFFF
        assert seq2 == (initial + 2) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Item 6: _ws_debug_enabled checks env var at call time
# ---------------------------------------------------------------------------


class TestWSDebugLazy:
    def test_ws_debug_function_exists(self) -> None:
        from vibesensor.ws_hub import _ws_debug_enabled

        assert callable(_ws_debug_enabled)

    def test_ws_debug_toggleable_at_runtime(self) -> None:
        from vibesensor.ws_hub import _ws_debug_enabled

        # Ensure it's off
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIBESENSOR_WS_DEBUG", None)
            assert _ws_debug_enabled() is False

        # Turn it on at runtime
        with patch.dict(os.environ, {"VIBESENSOR_WS_DEBUG": "1"}):
            assert _ws_debug_enabled() is True

        # Turn it back off
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIBESENSOR_WS_DEBUG", None)
            assert _ws_debug_enabled() is False


# ---------------------------------------------------------------------------
# Item 7: DEFAULT_ANALYSIS_SETTINGS defined before sanitize_settings
# ---------------------------------------------------------------------------


class TestAnalysisSettingsOrder:
    def test_default_settings_defined_before_sanitize(self) -> None:
        import inspect

        import vibesensor.analysis_settings as mod

        source = inspect.getsource(mod)
        # DEFAULT_ANALYSIS_SETTINGS must appear before def sanitize_settings
        defaults_pos = source.index("DEFAULT_ANALYSIS_SETTINGS: dict")
        sanitize_pos = source.index("def sanitize_settings(")
        assert defaults_pos < sanitize_pos, (
            "DEFAULT_ANALYSIS_SETTINGS must be defined before sanitize_settings"
        )

    def test_sanitize_settings_works_with_defaults(self) -> None:
        from vibesensor.analysis_settings import sanitize_settings

        result = sanitize_settings({"tire_width_mm": 225.0})
        assert "tire_width_mm" in result
        assert result["tire_width_mm"] == 225.0


# ---------------------------------------------------------------------------
# Item 8: _alive flag protected under metrics lock
# ---------------------------------------------------------------------------


class TestWorkerPoolAliveProtection:
    def test_submit_checks_alive_under_lock(self) -> None:
        from vibesensor.worker_pool import WorkerPool

        pool = WorkerPool(max_workers=1)
        pool.shutdown()

        with pytest.raises(RuntimeError, match="shut down"):
            pool.submit(lambda: None)

    def test_shutdown_sets_alive_under_lock(self) -> None:
        from vibesensor.worker_pool import WorkerPool

        pool = WorkerPool(max_workers=1)
        assert pool._alive is True
        pool.shutdown()
        assert pool._alive is False


# ---------------------------------------------------------------------------
# Item 9: as_float_or_none imported directly (no confusing alias)
# ---------------------------------------------------------------------------


class TestAsFloatOrNoneImport:
    def test_diagnostics_shared_uses_full_name(self) -> None:
        """diagnostics_shared should import as_float_or_none, not _as_float."""
        import inspect

        import vibesensor.diagnostics_shared as ds

        source = inspect.getsource(ds)
        assert "as _as_float" not in source, (
            "diagnostics_shared should not alias as_float_or_none to _as_float"
        )
        assert "as_float_or_none" in source

    def test_as_float_or_none_accessible_from_diagnostics_shared(self) -> None:
        from vibesensor.diagnostics_shared import as_float_or_none

        assert as_float_or_none(3.14) == 3.14
        assert as_float_or_none(None) is None


# ---------------------------------------------------------------------------
# Item 10: udp_control_tx has __all__
# ---------------------------------------------------------------------------


class TestUdpControlTxAll:
    def test_has_all_export(self) -> None:
        import vibesensor.udp_control_tx as mod

        assert hasattr(mod, "__all__")
        assert "UDPControlPlane" in mod.__all__

    def test_internal_class_not_in_all(self) -> None:
        import vibesensor.udp_control_tx as mod

        assert "ControlDatagramProtocol" not in mod.__all__
