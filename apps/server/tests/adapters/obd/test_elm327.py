from __future__ import annotations

import pytest

from vibesensor.adapters.obd.elm327 import (
    elm_response_has_no_data,
    normalize_elm_response,
    parse_pid_010c_rpm,
    parse_pid_010d_speed_kmh,
)


def test_normalize_elm_response_strips_echo_and_prompt() -> None:
    raw = b"010D\r\r410D28\r>"

    assert normalize_elm_response("010D", raw) == "410D28"


def test_parse_pid_010d_speed_kmh_accepts_compact_response() -> None:
    assert parse_pid_010d_speed_kmh("SEARCHING...\r410D28") == pytest.approx(40.0)


@pytest.mark.parametrize("response", ["NO DATA", "STOPPED"])
def test_parse_pid_010d_speed_kmh_returns_none_for_no_data(response: str) -> None:
    assert elm_response_has_no_data(response)
    assert parse_pid_010d_speed_kmh(response) is None


def test_parse_pid_010c_rpm_accepts_spaced_hex_response() -> None:
    assert parse_pid_010c_rpm("41 0C 1A F8") == pytest.approx(0x1AF8 / 4.0)
