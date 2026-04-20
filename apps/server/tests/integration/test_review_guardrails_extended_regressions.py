"""Cross-cutting review guardrail regressions (extended set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

import os
import threading
import time
from unittest.mock import patch

import pytest
from test_support.gps import set_gps_snapshot_age

import vibesensor.adapters.udp.udp_control_tx as udp_control_tx_mod
import vibesensor.shared.locations as locations_mod
from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
from vibesensor.adapters.persistence.car_library import (
    get_models_for_brand_type,
    get_variants_for_model,
    load_car_library,
)
from vibesensor.adapters.udp.udp_control_tx import UDPControlPlane
from vibesensor.adapters.websocket.hub import _ws_debug_enabled
from vibesensor.infra.runtime.registry import ClientRegistry
from vibesensor.infra.workers.worker_pool import WorkerPool
from vibesensor.shared.locations import is_wheel_location
from vibesensor.shared.order_bands import (
    as_float_or_none as order_bands_as_float_or_none,
)


def _make_gps_monitor() -> GPSSpeedMonitor:
    return GPSSpeedMonitor(gps_enabled=True)


def _make_control_plane() -> UDPControlPlane:
    return UDPControlPlane(ClientRegistry(), "127.0.0.1", 0)


# ---------------------------------------------------------------------------
# Item 1: _NON_WHEEL_TOKENS is a module-level constant
# ---------------------------------------------------------------------------


class TestNonWheelTokensModuleLevel:
    """Verify non-wheel classification tokens stay module-scoped and effective."""

    def test_non_wheel_tokens_is_module_constant(self) -> None:
        assert hasattr(locations_mod, "_NON_WHEEL_TOKENS")
        assert isinstance(locations_mod._NON_WHEEL_TOKENS, tuple)
        assert "seat" in locations_mod._NON_WHEEL_TOKENS
        assert "trunk" in locations_mod._NON_WHEEL_TOKENS

    @pytest.mark.parametrize(
        ("location", "expected"),
        [
            ("driver_seat", False),
            ("transmission", False),
            ("front_left_wheel", True),
        ],
    )
    def test_is_wheel_location_classification(self, location: str, expected: bool) -> None:
        assert is_wheel_location(location) is expected


# ---------------------------------------------------------------------------
# Item 2: resolve_speed reads from atomic snapshot
# ---------------------------------------------------------------------------


class TestResolveSpeedAtomicSnapshot:
    """Verify GPS speed resolution reads from and updates the atomic snapshot."""

    def test_speed_mps_property_reads_from_snapshot(self) -> None:
        m = _make_gps_monitor()
        assert m.speed_mps is None
        m.speed_mps = 10.0
        assert m.speed_mps == 10.0
        assert m._speed_snapshot[0] == 10.0

    def test_speed_mps_setter_refreshes_timestamp(self) -> None:
        m = _make_gps_monitor()
        ts = time.monotonic()
        m._speed_snapshot = (5.0, ts)
        m.speed_mps = 10.0
        assert m._speed_snapshot[0] == 10.0
        assert m._speed_snapshot[1] is not None
        assert m._speed_snapshot[1] > ts

    def test_resolve_speed_uses_snapshot_speed(self) -> None:
        m = _make_gps_monitor()
        # Write speed and timestamp atomically
        m._speed_snapshot = (10.0, time.monotonic())
        r = m.resolve_speed()
        assert r.speed_mps == 10.0
        assert r.source == "gps"

    def test_resolve_speed_snapshot_consistency(self) -> None:
        """Setting speed_mps and the test snapshot helper both update the snapshot."""
        m = _make_gps_monitor()
        m.speed_mps = 15.0
        set_gps_snapshot_age(m)
        r = m.resolve_speed()
        assert r.speed_mps == 15.0
        assert r.source == "gps"


# ---------------------------------------------------------------------------
# Item 4: car library returns copies
# ---------------------------------------------------------------------------


class TestCarLibraryCopies:
    """Verify car-library query helpers return copies rather than mutable internals."""

    def test_get_models_returns_copies(self) -> None:
        library = load_car_library()
        if not library:
            pytest.skip("No car library data loaded")
        brand = library[0].get("brand")
        car_type = library[0].get("type")
        models = get_models_for_brand_type(brand, car_type)
        if not models:
            pytest.skip("No models found")
        # Mutate the returned dict
        models[0]["MUTATED"] = True
        # Original library should NOT be mutated
        for entry in load_car_library():
            assert "MUTATED" not in entry

    def test_get_variants_returns_copies(self) -> None:
        library = load_car_library()
        if not library:
            pytest.skip("No car library data loaded")
        for entry in library:
            variants = entry.get("variants") or []
            if variants:
                result = get_variants_for_model(entry["brand"], entry["type"], entry["model"])
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
    """Verify UDP control sequence generation remains lock-protected and monotonic."""

    def test_udp_control_plane_has_cmd_seq_lock(self) -> None:
        cp = _make_control_plane()
        assert hasattr(cp, "_cmd_seq_lock")
        assert isinstance(cp._cmd_seq_lock, type(threading.Lock()))

    def test_next_cmd_seq_increments_atomically(self) -> None:
        cp = _make_control_plane()
        initial = cp._cmd_seq
        seq1 = cp._next_cmd_seq()
        seq2 = cp._next_cmd_seq()
        assert seq1 == (initial + 1) & 0xFFFFFFFF
        assert seq2 == (initial + 2) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Item 6: _ws_debug_enabled checks env var at call time
# ---------------------------------------------------------------------------


class TestWSDebugLazy:
    """Verify WebSocket debug mode is determined from the environment at call time."""

    def test_ws_debug_function_exists(self) -> None:
        assert callable(_ws_debug_enabled)

    def test_ws_debug_toggleable_at_runtime(self) -> None:
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
# Item 8: _alive flag protected under metrics lock
# ---------------------------------------------------------------------------


class TestWorkerPoolAliveProtection:
    """Verify WorkerPool shutdown state is enforced through the locked alive flag."""

    def test_submit_checks_alive_under_lock(self) -> None:
        pool = WorkerPool(max_workers=1)
        pool.shutdown()

        with pytest.raises(RuntimeError, match="shut down"):
            pool.submit(lambda: None)

    def test_shutdown_sets_alive_under_lock(self) -> None:
        pool = WorkerPool(max_workers=1)
        assert pool._alive is True
        pool.shutdown()
        assert pool._alive is False


# ---------------------------------------------------------------------------
# Item 9: as_float_or_none imported directly (no confusing alias)
# ---------------------------------------------------------------------------


class TestAsFloatOrNoneImport:
    """Verify order-band float parsing remains exposed without extra alias layers."""

    def test_as_float_or_none_accessible_from_order_bands(self) -> None:
        assert order_bands_as_float_or_none(3.14) == 3.14
        assert order_bands_as_float_or_none(None) is None


# ---------------------------------------------------------------------------
# Item 10: udp_control_tx has __all__
# ---------------------------------------------------------------------------


class TestUdpControlTxAll:
    """Verify udp_control_tx keeps the intended public __all__ surface."""

    def test_has_all_export(self) -> None:
        assert hasattr(udp_control_tx_mod, "__all__")
        assert "UDPControlPlane" in udp_control_tx_mod.__all__

    def test_internal_class_not_in_all(self) -> None:
        assert "ControlDatagramProtocol" not in udp_control_tx_mod.__all__
