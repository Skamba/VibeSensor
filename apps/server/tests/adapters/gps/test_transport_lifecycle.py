"""Tests for transport_lifecycle: reconnect policy and state transitions."""

from __future__ import annotations

import pytest

from vibesensor.adapters.gps.transport_lifecycle import (
    GPS_RECONNECT_DELAY_S,
    TransportLifecycle,
)


def test_on_connected_returns_connected_state_and_resets_backoff() -> None:
    lifecycle = TransportLifecycle(initial_delay=1.0)
    lifecycle.on_connection_error(RuntimeError("boom"))
    assert lifecycle.reconnect_delay > 1.0

    transition = lifecycle.on_connected()

    assert transition.changes == {
        "connection_state": "connected",
        "last_error": None,
        "current_reconnect_delay": 1.0,
    }
    assert transition.sleep_before_retry is None
    assert lifecycle.reconnect_delay == 1.0


def test_on_stream_disconnected_returns_disconnected_fields_and_resets_backoff() -> None:
    lifecycle = TransportLifecycle(initial_delay=0.5)
    lifecycle.on_connection_error(RuntimeError("x"))

    transition = lifecycle.on_stream_disconnected()

    assert transition.changes == _expected_disconnected_fields()
    assert transition.sleep_before_retry is None
    assert lifecycle.reconnect_delay == 0.5


@pytest.mark.parametrize(
    ("exc", "expected_error"),
    [
        pytest.param(OSError("network down"), "network down", id="message"),
        pytest.param(ConnectionError(), "ConnectionError", id="type_name_fallback"),
    ],
)
def test_on_connection_error_returns_disconnected_error_transition(
    exc: BaseException,
    expected_error: str,
) -> None:
    lifecycle = TransportLifecycle(initial_delay=2.0)

    transition = lifecycle.on_connection_error(exc)

    assert transition.changes == {
        **_expected_disconnected_fields(),
        "last_error": expected_error,
        "current_reconnect_delay": 2.0,
    }
    assert transition.sleep_before_retry == 2.0


@pytest.mark.parametrize(
    ("initial_delay", "max_delay", "backoff_factor", "expected_delays"),
    [
        pytest.param(1.0, 10.0, 2.0, [1.0, 2.0, 4.0, 8.0, 10.0], id="default_factor"),
        pytest.param(0.5, 2.0, 3.0, [0.5, 1.5, 2.0], id="custom_policy"),
    ],
)
def test_connection_error_advances_backoff_with_max_cap(
    initial_delay: float,
    max_delay: float,
    backoff_factor: float,
    expected_delays: list[float],
) -> None:
    lifecycle = TransportLifecycle(
        initial_delay=initial_delay,
        max_delay=max_delay,
        backoff_factor=backoff_factor,
    )

    transitions = [
        lifecycle.on_connection_error(RuntimeError(str(index)))
        for index in range(len(expected_delays))
    ]

    assert [transition.sleep_before_retry for transition in transitions] == expected_delays


def test_reset_delay_restores_initial_delay_after_backoff() -> None:
    lifecycle = TransportLifecycle(initial_delay=0.1)
    lifecycle.on_connection_error(RuntimeError("x"))
    lifecycle.on_connection_error(RuntimeError("y"))
    assert lifecycle.reconnect_delay > 0.1

    lifecycle.reset_delay()

    assert lifecycle.reconnect_delay == pytest.approx(0.1)


def test_default_policy_uses_module_reconnect_delay() -> None:
    lifecycle = TransportLifecycle()
    assert lifecycle.reconnect_delay == GPS_RECONNECT_DELAY_S
    transition = lifecycle.on_connected()
    assert transition.changes["current_reconnect_delay"] == GPS_RECONNECT_DELAY_S


def _expected_disconnected_fields() -> dict[str, object]:
    return {
        "connection_state": "disconnected",
        "speed_snapshot": (None, None),
        "last_fix_mode": None,
        "last_epx_m": None,
        "last_epy_m": None,
        "last_epv_m": None,
        "zero_speed_streak": 0,
        "device_info": None,
    }
