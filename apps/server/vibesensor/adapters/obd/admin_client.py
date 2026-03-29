"""Unprivileged client for the privileged Bluetooth OBD helper script."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from vibesensor.adapters.obd.models import ObdDeviceSnapshot

__all__ = ["CommandResult", "ObdAdminClient"]

_OBD_SUDO_HELPER_ERROR = (
    "Bluetooth OBD scan requires the Pi sudo helper and NOPASSWD sudoers entry "
    "to run non-interactively."
)
_OBD_HELPER_LAUNCH_ERROR = (
    "Bluetooth OBD helper failed before returning structured output. "
    "Verify the helper installation on the Pi and try again."
)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Captured subprocess result."""

    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str], int], CommandResult]


def _default_helper_script() -> Path:
    for root in Path(__file__).resolve().parents:
        candidate = root / "scripts" / "vibesensor_obd_admin.py"
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[3] / "scripts" / "vibesensor_obd_admin.py"


def _default_runner(argv: list[str], timeout_s: int) -> CommandResult:
    try:
        completed = subprocess.run(
            argv,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout_s,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required command is unavailable: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        stdout = str(exc.stdout or "").strip()
        stderr = str(exc.stderr or "").strip()
        raise RuntimeError(
            f"OBD helper timed out after {timeout_s}s"
            + (f": {stderr}" if stderr else "")
            + (f" ({stdout})" if stdout else "")
        ) from exc
    return CommandResult(
        returncode=int(completed.returncode),
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )


class ObdAdminClient:
    """Invoke the root-owned Bluetooth helper via ``sudo -n`` and parse JSON."""

    __slots__ = ("_helper_script", "_runner", "_sudo_path")

    def __init__(
        self,
        *,
        helper_script: Path | None = None,
        sudo_path: str = "sudo",
        runner: CommandRunner | None = None,
    ) -> None:
        self._helper_script = (
            _default_helper_script()
            if helper_script is None
            else Path(helper_script)
        )
        self._sudo_path = sudo_path
        self._runner = _default_runner if runner is None else runner

    def _run_helper(self, args: list[str], *, timeout_s: int) -> dict[str, Any]:
        argv = [self._sudo_path, "-n", str(self._helper_script), *args]
        result = self._runner(argv, timeout_s)
        launch_error = self._pre_json_failure(result)
        if launch_error is not None:
            raise RuntimeError(launch_error)
        raw_output = result.stdout or result.stderr or ""
        try:
            payload_raw = json.loads(raw_output or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Bluetooth OBD helper returned invalid JSON"
                + (f": {raw_output}" if raw_output else "")
            ) from exc
        if not isinstance(payload_raw, dict):
            raise RuntimeError("Bluetooth OBD helper returned a non-object JSON payload")
        payload = cast(dict[str, Any], payload_raw)
        if result.returncode != 0:
            error = str(
                payload.get("error")
                or result.stderr
                or result.stdout
                or "Bluetooth OBD helper failed"
            )
            raise RuntimeError(error)
        return payload

    @staticmethod
    def _pre_json_failure(result: CommandResult) -> str | None:
        if result.returncode == 0 or result.stdout:
            return None
        stderr = result.stderr.strip()
        if not stderr or stderr.lstrip().startswith("{"):
            return None
        lowered = stderr.lower()
        if (
            "sudo:" in lowered
            or "password is required" in lowered
            or "a terminal is required" in lowered
            or "no tty present" in lowered
        ):
            return _OBD_SUDO_HELPER_ERROR
        return _OBD_HELPER_LAUNCH_ERROR

    @staticmethod
    def _device_from_payload(raw: object) -> ObdDeviceSnapshot:
        if not isinstance(raw, dict):
            raise RuntimeError("Bluetooth OBD helper returned an invalid device payload")
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
            raise RuntimeError("Bluetooth OBD helper did not return a device list")
        return [self._device_from_payload(item) for item in devices_raw]

    def pair_device(self, mac_address: str) -> ObdDeviceSnapshot:
        payload = self._run_helper(["pair", mac_address], timeout_s=35)
        return self._device_from_payload(payload.get("device"))

    def device_info(self, mac_address: str) -> ObdDeviceSnapshot:
        payload = self._run_helper(["info", mac_address], timeout_s=15)
        return self._device_from_payload(payload.get("device"))
