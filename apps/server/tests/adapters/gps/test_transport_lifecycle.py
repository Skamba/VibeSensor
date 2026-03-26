"""Tests for transport_lifecycle: reconnect policy and state transitions."""

from __future__ import annotations

import pytest

from vibesensor.adapters.gps.transport_lifecycle import (
    GPS_RECONNECT_DELAY_S,
    TransportLifecycle,
)


class TestOnConnected:
    def test_returns_connected_state(self) -> None:
        lifecycle = TransportLifecycle()
        transition = lifecycle.on_connected()
        assert transition.changes["connection_state"] == "connected"
        assert transition.changes["last_error"] is None
        assert transition.changes["current_reconnect_delay"] == GPS_RECONNECT_DELAY_S
        assert transition.sleep_before_retry is None

    def test_resets_backoff_delay(self) -> None:
        lifecycle = TransportLifecycle(initial_delay=1.0)
        # Advance backoff first.
        lifecycle.on_connection_error(RuntimeError("boom"))
        assert lifecycle.reconnect_delay > 1.0
        # on_connected resets it.
        lifecycle.on_connected()
        assert lifecycle.reconnect_delay == 1.0


class TestOnStreamDisconnected:
    def test_returns_disconnected_fields(self) -> None:
        lifecycle = TransportLifecycle()
        transition = lifecycle.on_stream_disconnected()
        assert transition.changes["connection_state"] == "disconnected"
        assert transition.changes["speed_snapshot"] == (None, None)
        assert transition.changes["last_fix_mode"] is None
        assert transition.changes["device_info"] is None
        assert transition.changes["zero_speed_streak"] == 0
        assert transition.sleep_before_retry is None

    def test_resets_backoff_delay(self) -> None:
        lifecycle = TransportLifecycle(initial_delay=0.5)
        lifecycle.on_connection_error(RuntimeError("x"))
        lifecycle.on_stream_disconnected()
        assert lifecycle.reconnect_delay == 0.5


class TestOnConnectionError:
    def test_returns_disconnected_plus_error(self) -> None:
        lifecycle = TransportLifecycle(initial_delay=2.0)
        exc = OSError("network down")
        transition = lifecycle.on_connection_error(exc)
        assert transition.changes["connection_state"] == "disconnected"
        assert transition.changes["last_error"] == "network down"
        assert transition.changes["current_reconnect_delay"] == 2.0
        assert transition.sleep_before_retry == 2.0

    def test_error_str_fallback_to_type_name(self) -> None:
        lifecycle = TransportLifecycle()
        transition = lifecycle.on_connection_error(ConnectionError())
        assert transition.changes["last_error"] == "ConnectionError"

    def test_exponential_backoff(self) -> None:
        lifecycle = TransportLifecycle(initial_delay=1.0, max_delay=10.0, backoff_factor=2.0)
        first_transition = lifecycle.on_connection_error(RuntimeError("a"))
        assert first_transition.sleep_before_retry == 1.0
        second_transition = lifecycle.on_connection_error(RuntimeError("b"))
        assert second_transition.sleep_before_retry == 2.0
        third_transition = lifecycle.on_connection_error(RuntimeError("c"))
        assert third_transition.sleep_before_retry == 4.0
        fourth_transition = lifecycle.on_connection_error(RuntimeError("d"))
        assert fourth_transition.sleep_before_retry == 8.0
        # Capped at max.
        fifth_transition = lifecycle.on_connection_error(RuntimeError("e"))
        assert fifth_transition.sleep_before_retry == 10.0

    def test_clears_gps_metadata(self) -> None:
        lifecycle = TransportLifecycle()
        transition = lifecycle.on_connection_error(TimeoutError())
        assert transition.changes["last_epx_m"] is None
        assert transition.changes["last_epy_m"] is None
        assert transition.changes["last_epv_m"] is None
        assert transition.changes["last_fix_mode"] is None


class TestResetDelay:
    def test_resets_after_backoff(self) -> None:
        lifecycle = TransportLifecycle(initial_delay=0.1)
        lifecycle.on_connection_error(RuntimeError("x"))
        lifecycle.on_connection_error(RuntimeError("y"))
        assert lifecycle.reconnect_delay > 0.1
        lifecycle.reset_delay()
        assert lifecycle.reconnect_delay == pytest.approx(0.1)


class TestCustomPolicy:
    def test_custom_initial_and_max(self) -> None:
        lifecycle = TransportLifecycle(initial_delay=0.5, max_delay=2.0, backoff_factor=3.0)
        first_transition = lifecycle.on_connection_error(RuntimeError("a"))
        assert first_transition.sleep_before_retry == 0.5
        second_transition = lifecycle.on_connection_error(RuntimeError("b"))
        assert second_transition.sleep_before_retry == 1.5
        # Next would be 4.5 but capped at 2.0.
        third_transition = lifecycle.on_connection_error(RuntimeError("c"))
        assert third_transition.sleep_before_retry == 2.0

    def test_defaults_match_module_constants(self) -> None:
        lifecycle = TransportLifecycle()
        assert lifecycle.reconnect_delay == GPS_RECONNECT_DELAY_S
        transition = lifecycle.on_connected()
        assert transition.changes["current_reconnect_delay"] == GPS_RECONNECT_DELAY_S
