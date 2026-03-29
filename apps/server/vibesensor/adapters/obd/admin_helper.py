"""Privileged Bluetooth OBD admin helper implementation."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, replace
from typing import Any

from vibesensor.adapters.obd.common import bluetooth_mac_address, normalize_obd_mac
from vibesensor.adapters.obd.models import ObdDeviceSnapshot

__all__ = [
    "BluetoothObdAdminHelper",
    "main",
    "parse_bluetooth_device_info",
    "parse_bluetooth_devices",
    "parse_rfcomm_channel",
]


class _HelperFailure(RuntimeError):
    """Raised when a privileged Bluetooth helper action fails."""


CommandRunner = Callable[[list[str], int, bool], tuple[int, str, str]]


def _coerce_text(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="ignore")
    return raw


def _default_runner(argv: list[str], timeout_s: int, allow_timeout: bool) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            argv,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout_s,
        )
    except FileNotFoundError as exc:
        raise _HelperFailure(f"Required command is unavailable: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        if not allow_timeout:
            raise _HelperFailure(f"Command timed out after {timeout_s}s: {' '.join(argv)}") from exc
        return 124, _coerce_text(exc.stdout).strip(), _coerce_text(exc.stderr).strip()
    return int(completed.returncode), completed.stdout.strip(), completed.stderr.strip()


def parse_bluetooth_devices(output: str) -> list[ObdDeviceSnapshot]:
    """Parse ``bluetoothctl devices``-style output."""
    devices: dict[str, ObdDeviceSnapshot] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("Device "):
            continue
        _, raw_mac, *name_parts = line.split()
        try:
            mac_address = normalize_obd_mac(raw_mac)
        except ValueError:
            continue
        name = " ".join(name_parts).strip() or None
        devices[mac_address] = ObdDeviceSnapshot(
            mac_address=mac_address,
            name=name,
            paired=False,
            trusted=False,
            connected=False,
            rfcomm_channel=None,
        )
    return list(devices.values())


def parse_bluetooth_device_info(output: str, mac_address: str) -> ObdDeviceSnapshot:
    """Parse ``bluetoothctl info`` output into an ``ObdDeviceSnapshot``."""
    name: str | None = None
    paired = False
    trusted = False
    connected = False
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("Name:"):
            name = line.partition(":")[2].strip() or name
        elif line.startswith("Alias:") and name is None:
            name = line.partition(":")[2].strip() or None
        elif line.startswith("Paired:"):
            paired = line.partition(":")[2].strip().lower() == "yes"
        elif line.startswith("Trusted:"):
            trusted = line.partition(":")[2].strip().lower() == "yes"
        elif line.startswith("Connected:"):
            connected = line.partition(":")[2].strip().lower() == "yes"
    return ObdDeviceSnapshot(
        mac_address=normalize_obd_mac(mac_address),
        name=name,
        paired=paired,
        trusted=trusted,
        connected=connected,
        rfcomm_channel=None,
    )


def parse_rfcomm_channel(output: str) -> int | None:
    """Return the first advertised RFCOMM channel from ``sdptool browse`` output."""
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.lower().startswith("channel:"):
            continue
        _, _, value = line.partition(":")
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


class BluetoothObdAdminHelper:
    """Root-only helper for scanning, pairing, and inspecting Bluetooth OBD adapters."""

    __slots__ = ("_runner",)

    def __init__(self, *, runner: CommandRunner | None = None) -> None:
        self._runner = _default_runner if runner is None else runner

    def _run(self, argv: list[str], *, timeout_s: int, allow_timeout: bool = False) -> str:
        returncode, stdout, stderr = self._runner(argv, timeout_s, allow_timeout)
        if returncode not in (0, 124):
            message = stderr or stdout or f"Command failed: {' '.join(argv)}"
            raise _HelperFailure(message)
        return stdout or stderr

    def _bluetoothctl(
        self,
        *args: str,
        timeout_s: int,
        allow_timeout: bool = False,
        ignore_errors: bool = False,
    ) -> str:
        try:
            return self._run(
                ["bluetoothctl", *args],
                timeout_s=timeout_s,
                allow_timeout=allow_timeout,
            )
        except _HelperFailure:
            if ignore_errors:
                return ""
            raise

    def _prepare_controller(self) -> None:
        self._run(["rfkill", "unblock", "bluetooth"], timeout_s=5, allow_timeout=False)
        self._run(["systemctl", "start", "bluetooth"], timeout_s=10, allow_timeout=False)
        self._bluetoothctl("power", "on", timeout_s=10)

    def device_info(self, mac_address: str, *, ensure_ready: bool = True) -> ObdDeviceSnapshot:
        normalized = normalize_obd_mac(mac_address)
        if ensure_ready:
            self._prepare_controller()
        bt_mac = bluetooth_mac_address(normalized)
        info_output = self._bluetoothctl("info", bt_mac, timeout_s=8, ignore_errors=True)
        device = parse_bluetooth_device_info(info_output, normalized)
        try:
            channel_output = self._run(
                ["sdptool", "browse", bt_mac],
                timeout_s=10,
                allow_timeout=False,
            )
        except _HelperFailure:
            channel = None
        else:
            channel = parse_rfcomm_channel(channel_output)
        return replace(device, rfcomm_channel=channel)

    def scan_devices(self, *, timeout_s: int) -> list[ObdDeviceSnapshot]:
        self._prepare_controller()
        self._bluetoothctl("scan", "on", timeout_s=max(3, timeout_s), allow_timeout=True)
        try:
            devices = {
                device.mac_address: device
                for device in parse_bluetooth_devices(
                    self._bluetoothctl("devices", timeout_s=5, ignore_errors=True)
                )
            }
            paired_devices = {
                device.mac_address
                for device in parse_bluetooth_devices(
                    self._bluetoothctl("paired-devices", timeout_s=5, ignore_errors=True)
                )
            }
        finally:
            self._bluetoothctl("scan", "off", timeout_s=5, ignore_errors=True)
        resolved: list[ObdDeviceSnapshot] = []
        for device in devices.values():
            if device.mac_address in paired_devices:
                try:
                    detailed = self.device_info(device.mac_address, ensure_ready=False)
                except _HelperFailure:
                    detailed = replace(device, paired=True)
                else:
                    if detailed.name is None and device.name is not None:
                        detailed = replace(detailed, name=device.name)
                resolved.append(detailed)
            else:
                resolved.append(device)
        return sorted(
            resolved,
            key=lambda device: (
                not device.connected,
                not device.paired,
                (device.name or device.mac_address).lower(),
            ),
        )

    def pair_device(self, mac_address: str) -> ObdDeviceSnapshot:
        normalized = normalize_obd_mac(mac_address)
        self._prepare_controller()
        bt_mac = bluetooth_mac_address(normalized)
        self._bluetoothctl("agent", "on", timeout_s=5, ignore_errors=True)
        self._bluetoothctl("default-agent", timeout_s=5, ignore_errors=True)
        self._bluetoothctl("pair", bt_mac, timeout_s=25, ignore_errors=True)
        self._bluetoothctl("trust", bt_mac, timeout_s=10, ignore_errors=True)
        self._bluetoothctl("connect", bt_mac, timeout_s=15, ignore_errors=True)
        device = self.device_info(normalized, ensure_ready=False)
        if not device.paired:
            raise _HelperFailure("Bluetooth OBD pairing did not complete successfully")
        if not device.trusted:
            raise _HelperFailure("Bluetooth OBD adapter paired, but trust setup failed")
        return device


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Privileged Bluetooth OBD admin helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Scan for nearby Bluetooth OBD adapters")
    scan.add_argument("--timeout", type=int, default=8)

    pair = subparsers.add_parser("pair", help="Pair/trust/connect a Bluetooth OBD adapter")
    pair.add_argument("mac_address")

    info = subparsers.add_parser("info", help="Return Bluetooth and RFCOMM info for one adapter")
    info.add_argument("mac_address")
    return parser


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    helper = BluetoothObdAdminHelper()
    try:
        if args.command == "scan":
            devices = helper.scan_devices(timeout_s=max(3, int(args.timeout)))
            _print_json(
                {
                    "devices": [asdict(device) for device in devices],
                    "scan_timeout_s": max(3, int(args.timeout)),
                }
            )
            return 0
        if args.command == "pair":
            device = helper.pair_device(args.mac_address)
            _print_json({"device": asdict(device)})
            return 0
        if args.command == "info":
            device = helper.device_info(args.mac_address)
            _print_json({"device": asdict(device)})
            return 0
        raise _HelperFailure(f"Unsupported command: {args.command}")
    except (ValueError, _HelperFailure) as exc:
        _print_json({"error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
