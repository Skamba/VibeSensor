from __future__ import annotations

import json

import pytest

from vibesensor.common.operational_errors import ExternalCommandError
from vibesensor.common.privileged_helper import PrivilegedResult
from vibesensor.speed.obd.admin_client import ObdAdminClient


def test_scan_devices_sends_helper_args_and_parses_json() -> None:
    calls: list[tuple[list[str], int]] = []

    def runner(argv: list[str], timeout_s: int) -> PrivilegedResult:
        calls.append((argv, timeout_s))
        return PrivilegedResult(
            returncode=0,
            stdout=json.dumps(
                {
                    "devices": [
                        {
                            "mac_address": "02000000004d",
                            "name": "OBDLink MX+",
                            "paired": True,
                            "trusted": True,
                            "connected": False,
                            "rfcomm_channel": 1,
                        }
                    ]
                }
            ),
            stderr="",
        )

    client = ObdAdminClient(runner=runner)

    devices = client.scan_devices(timeout_s=9)

    assert calls == [(["scan", "--timeout", "9"], 27)]
    assert devices[0].mac_address == "02000000004d"
    assert devices[0].name == "OBDLink MX+"
    assert devices[0].rfcomm_channel == 1


def test_pair_device_raises_operational_error_from_helper_json() -> None:

    def runner(argv: list[str], timeout_s: int) -> PrivilegedResult:
        del argv, timeout_s
        return PrivilegedResult(
            returncode=1,
            stdout=json.dumps({"error": "Bluetooth OBD pairing failed"}),
            stderr="",
        )

    client = ObdAdminClient(runner=runner)

    with pytest.raises(ExternalCommandError, match="Bluetooth OBD pairing failed"):
        client.pair_device("02000000004d")


def test_scan_devices_reports_helper_launch_failure_with_its_stderr() -> None:
    def runner(argv: list[str], timeout_s: int) -> PrivilegedResult:
        del argv, timeout_s
        return PrivilegedResult(
            returncode=1,
            stdout="",
            stderr="Missing expected virtualenv interpreter",
        )

    client = ObdAdminClient(runner=runner)

    with pytest.raises(
        ExternalCommandError,
        match=r"failed before returning structured output.*\(Missing expected virtualenv",
    ):
        client.scan_devices()


def test_scan_devices_still_reports_invalid_json_when_stdout_is_malformed() -> None:

    def runner(argv: list[str], timeout_s: int) -> PrivilegedResult:
        del argv, timeout_s
        return PrivilegedResult(
            returncode=0,
            stdout="Traceback (most recent call last):",
            stderr="",
        )

    client = ObdAdminClient(runner=runner)

    with pytest.raises(ExternalCommandError, match="Bluetooth OBD helper returned invalid JSON"):
        client.scan_devices()
