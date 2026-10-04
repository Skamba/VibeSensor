"""A sensor's reported firmware against the firmware bundled on the Pi."""

from __future__ import annotations

import pytest

from vibesensor.domain.sensor_firmware import firmware_status

_BUNDLED = "2026.10.5.2+0123456789ab"


@pytest.mark.parametrize(
    ("reported", "bundled", "expected"),
    [
        pytest.param(_BUNDLED, _BUNDLED, "current", id="same-build"),
        pytest.param(f" {_BUNDLED} ", _BUNDLED, "current", id="padded"),
        pytest.param("esp32-atom-0.1", _BUNDLED, "outdated", id="pre-stamp-firmware"),
        pytest.param("2026.10.5.1+aaaaaaaaaaaa", _BUNDLED, "outdated", id="older-release"),
        pytest.param("2026.9.30+aaaaaaaaaaaa", _BUNDLED, "outdated", id="older-month"),
        pytest.param("2026.10.5.10+aaaaaaaaaaaa", _BUNDLED, "unknown", id="newer-release"),
        pytest.param("0.0.0-dev+aaaaaaaaaaaa", _BUNDLED, "unknown", id="dev-build"),
        pytest.param("esp32-atom-0.1", "", "unknown", id="no-bundle-version"),
        pytest.param("", _BUNDLED, "unknown", id="no-hello-yet"),
        pytest.param(
            "2026.10.5+aaaaaaaaaaaa", "0.0.0-dev+0123456789ab", "unknown", id="dev-bundle"
        ),
    ],
)
def test_firmware_status(reported: str, bundled: str, expected: str) -> None:
    assert firmware_status(reported, bundled) == expected
