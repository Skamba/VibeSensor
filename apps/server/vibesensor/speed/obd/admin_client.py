"""Unprivileged client for the root-side Bluetooth OBD helper."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

from vibesensor.common.operational_errors import ExternalCommandError
from vibesensor.common.privileged_helper import OBD_HELPER, PrivilegedResult, run_privileged
from vibesensor.speed.obd.models import ObdDeviceSnapshot

__all__ = ["ObdAdminClient"]

_OBD_HELPER_LAUNCH_ERROR = (
    "Bluetooth OBD helper failed before returning structured output. "
    "Verify the helper installation on the Pi and try again."
)

CommandRunner = Callable[[list[str], int], PrivilegedResult]


def _default_runner(args: list[str], timeout_s: int) -> PrivilegedResult:
    return run_privileged(OBD_HELPER, args, timeout_s=timeout_s)


class ObdAdminClient:
    """Run ``vibesensor_obd_admin.py`` as root via the privileged helper and parse JSON."""

    __slots__ = ("_runner",)

    def __init__(self, *, runner: CommandRunner | None = None) -> None:
        self._runner = _default_runner if runner is None else runner

    def _run_helper(self, args: list[str], *, timeout_s: int) -> dict[str, Any]:
        result = self._runner(args, timeout_s)
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        if result.returncode != 0 and not stdout and stderr and not stderr.startswith("{"):
            raise ExternalCommandError(f"{_OBD_HELPER_LAUNCH_ERROR} ({stderr})")
        raw_output = stdout or stderr
        try:
            payload_raw = json.loads(raw_output or "{}")
        except json.JSONDecodeError as exc:
            raise ExternalCommandError(
                "Bluetooth OBD helper returned invalid JSON"
                + (f": {raw_output}" if raw_output else "")
            ) from exc
        if not isinstance(payload_raw, dict):
            raise ExternalCommandError("Bluetooth OBD helper returned a non-object JSON payload")
        payload = cast(dict[str, Any], payload_raw)
        if result.returncode != 0:
            error = str(payload.get("error") or stderr or stdout or "Bluetooth OBD helper failed")
            raise ExternalCommandError(error)
        return payload

    @staticmethod
    def _device_from_payload(raw: object) -> ObdDeviceSnapshot:
        if not isinstance(raw, dict):
            raise ExternalCommandError("Bluetooth OBD helper returned an invalid device payload")
        channel_raw = raw.get("rfcomm_channel")
        channel = int(channel_raw) if isinstance(channel_raw, int) else None
        return ObdDeviceSnapshot(
            mac_address=str(raw.get("mac_address") or ""),
            name=(str(raw.get("name")) if raw.get("name") not in (None, "") else None),
            paired=bool(raw.get("paired", False)),
            trusted=bool(raw.get("trusted", False)),
            connected=bool(raw.get("connected", False)),
            rfcomm_channel=channel,
        )

    def scan_devices(self, *, timeout_s: int = 8) -> list[ObdDeviceSnapshot]:
        payload = self._run_helper(
            ["scan", "--timeout", str(max(3, timeout_s))],
            timeout_s=max(15, timeout_s + 8),
        )
        devices_raw = payload.get("devices")
        if not isinstance(devices_raw, list):
            raise ExternalCommandError("Bluetooth OBD helper did not return a device list")
        return [self._device_from_payload(item) for item in devices_raw]

    def pair_device(self, mac_address: str) -> ObdDeviceSnapshot:
        payload = self._run_helper(["pair", mac_address], timeout_s=35)
        return self._device_from_payload(payload.get("device"))

    def device_info(self, mac_address: str) -> ObdDeviceSnapshot:
        payload = self._run_helper(["info", mac_address], timeout_s=15)
        return self._device_from_payload(payload.get("device"))
