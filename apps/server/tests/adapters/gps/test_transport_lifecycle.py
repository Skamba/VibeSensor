"""Tests for transport_lifecycle: reconnect policy and state transitions."""

from __future__ import annotations

import pytest

from vibesensor.adapters.gps.transport_lifecycle import (
    GPS_RECONNECT_DELAY_S,
    TransportLifecycle,
)


class TestOnConnected:
    def test_returns_connected_state(self) -> None:
        lc = TransportLifecycle()
        t = lc.on_connected()
        assert t.changes["connection_state"] == "connected"
        assert t.changes["last_error"] is None
        assert t.changes["current_reconnect_delay"] == GPS_RECONNECT_DELAY_S
        assert t.sleep_before_retry is None

    def test_resets_backoff_delay(self) -> None:
        lc = TransportLifecycle(initial_delay=1.0)
        # Advance backoff first.
        lc.on_connection_error(RuntimeError("boom"))
        assert lc.reconnect_delay > 1.0
        # on_connected resets it.
        lc.on_connected()
        assert lc.reconnect_delay == 1.0


class TestOnStreamDisconnected:
    def test_returns_disconnected_fields(self) -> None:
        lc = TransportLifecycle()
        t = lc.on_stream_disconnected()
        assert t.changes["connection_state"] == "disconnected"
        assert t.changes["speed_snapshot"] == (None, None)
        assert t.changes["last_fix_mode"] is None
        assert t.changes["device_info"] is None
        assert t.changes["zero_speed_streak"] == 0
        assert t.sleep_before_retry is None

    def test_resets_backoff_delay(self) -> None:
        lc = TransportLifecycle(initial_delay=0.5)
        lc.on_connection_error(RuntimeError("x"))
        lc.on_stream_disconnected()
        assert lc.reconnect_delay == 0.5


class TestOnConnectionError:
    def test_returns_disconnected_plus_error(self) -> None:
        lc = TransportLifecycle(initial_delay=2.0)
        exc = OSError("network down")
        t = lc.on_connection_error(exc)
        assert t.changes["connection_state"] == "disconnected"
        assert t.changes["last_error"] == "network down"
        assert t.changes["current_reconnect_delay"] == 2.0
        assert t.sleep_before_retry == 2.0

    def test_error_str_fallback_to_type_name(self) -> None:
        lc = TransportLifecycle()
        t = lc.on_connection_error(ConnectionError())
        assert t.changes["last_error"] == "ConnectionError"

    def test_exponential_backoff(self) -> None:
        lc = TransportLifecycle(initial_delay=1.0, max_delay=10.0, backoff_factor=2.0)
        t1 = lc.on_connection_error(RuntimeError("a"))
        assert t1.sleep_before_retry == 1.0
        t2 = lc.on_connection_error(RuntimeError("b"))
        assert t2.sleep_before_retry == 2.0
        t3 = lc.on_connection_error(RuntimeError("c"))
        assert t3.sleep_before_retry == 4.0
        t4 = lc.on_connection_error(RuntimeError("d"))
        assert t4.sleep_before_retry == 8.0
        # Capped at max.
        t5 = lc.on_connection_error(RuntimeError("e"))
        assert t5.sleep_before_retry == 10.0

    def test_clears_gps_metadata(self) -> None:
        lc = TransportLifecycle()
        t = lc.on_connection_error(TimeoutError())
        assert t.changes["last_epx_m"] is None
        assert t.changes["last_epy_m"] is None
        assert t.changes["last_epv_m"] is None
        assert t.changes["last_fix_mode"] is None


class TestResetDelay:
    def test_resets_after_backoff(self) -> None:
        lc = TransportLifecycle(initial_delay=0.1)
        lc.on_connection_error(RuntimeError("x"))
        lc.on_connection_error(RuntimeError("y"))
        assert lc.reconnect_delay > 0.1
        lc.reset_delay()
        assert lc.reconnect_delay == pytest.approx(0.1)


class TestCustomPolicy:
    def test_custom_initial_and_max(self) -> None:
        lc = TransportLifecycle(initial_delay=0.5, max_delay=2.0, backoff_factor=3.0)
        t1 = lc.on_connection_error(RuntimeError("a"))
        assert t1.sleep_before_retry == 0.5
        t2 = lc.on_connection_error(RuntimeError("b"))
        assert t2.sleep_before_retry == 1.5
        # Next would be 4.5 but capped at 2.0.
        t3 = lc.on_connection_error(RuntimeError("c"))
        assert t3.sleep_before_retry == 2.0

    def test_defaults_match_module_constants(self) -> None:
        lc = TransportLifecycle()
        assert lc.reconnect_delay == GPS_RECONNECT_DELAY_S
        t = lc.on_connected()
        assert t.changes["current_reconnect_delay"] == GPS_RECONNECT_DELAY_S
