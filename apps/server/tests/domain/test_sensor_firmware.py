"""A sensor's reported firmware against the firmware bundled on the Pi."""

from __future__ import annotations

import pytest

from vibesensor.domain.sensor_firmware import firmware_status

_BUNDLED = "fw-20261005.1200+0123456789ab"


@pytest.mark.parametrize(
    ("reported", "bundled", "expected"),
    [
        pytest.param(_BUNDLED, _BUNDLED, "current", id="same-build"),
        pytest.param(f" {_BUNDLED} ", _BUNDLED, "current", id="padded"),
        pytest.param(
            "fw-20261001.0800+0123456789ab", _BUNDLED, "current", id="same-inputs-other-date"
        ),
        pytest.param(
            "fw-00000000.0000+0123456789ab", _BUNDLED, "current", id="same-inputs-no-git-date"
        ),
        pytest.param("fw-20261004.2359+aaaaaaaaaaaa", _BUNDLED, "outdated", id="older-firmware"),
        pytest.param("fw-20261005.1201+aaaaaaaaaaaa", _BUNDLED, "unknown", id="newer-firmware"),
        pytest.param("fw-20261005.1200+aaaaaaaaaaaa", _BUNDLED, "unknown", id="uncommitted-build"),
        # Firmware stamped with the server release before identities existed.
        pytest.param("2026.10.4.36+444e90c6c19d", _BUNDLED, "outdated", id="release-stamp"),
        pytest.param("2026.10.6.1+444e90c6c19d", _BUNDLED, "outdated", id="later-release-stamp"),
        pytest.param("0.0.0-dev+aaaaaaaaaaaa", _BUNDLED, "outdated", id="old-dev-stamp"),
        pytest.param("esp32-atom-0.1", _BUNDLED, "outdated", id="pre-stamp-firmware"),
        pytest.param("��", _BUNDLED, "outdated", id="garbled"),
        pytest.param(
            "fw-20261005.1200+0123456789ab", "2026.10.4.36+444e90c6c19d", "unknown", id="old-bundle"
        ),
        pytest.param("esp32-atom-0.1", "", "unknown", id="no-bundle-version"),
        pytest.param("", _BUNDLED, "unknown", id="no-hello-yet"),
    ],
)
def test_firmware_status(reported: str, bundled: str, expected: str) -> None:
    assert firmware_status(reported, bundled) == expected
