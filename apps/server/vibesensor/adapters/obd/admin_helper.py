"""Privileged Bluetooth OBD admin helper implementation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from vibesensor.adapters.obd.models import ObdDeviceSnapshot

from .admin_bluetooth import BluetoothAdminSession, CommandRunner, HelperFailure
from .admin_inspection import BluetoothObdDeviceInspector
from .admin_pairing import BluetoothObdPairer
from .admin_scan import BluetoothObdScanner

__all__ = ["BluetoothObdAdminHelper", "main"]


class BluetoothObdAdminHelper:
    """Root-only helper facade over focused Bluetooth OBD admin services."""

    __slots__ = ("_inspector", "_pairer", "_scanner")

    def __init__(self, *, runner: CommandRunner | None = None) -> None:
        bluetooth = BluetoothAdminSession(runner=runner)
        inspector = BluetoothObdDeviceInspector(bluetooth=bluetooth)
        self._inspector = inspector
        self._scanner = BluetoothObdScanner(bluetooth=bluetooth, inspector=inspector)
        self._pairer = BluetoothObdPairer(bluetooth=bluetooth, inspector=inspector)

    def device_info(
        self,
        mac_address: str,
        *,
        ensure_ready: bool = True,
        resolve_rfcomm: bool = True,
    ) -> ObdDeviceSnapshot:
        return self._inspector.device_info(
            mac_address,
            ensure_ready=ensure_ready,
            resolve_rfcomm=resolve_rfcomm,
        )

    def scan_devices(self, *, timeout_s: int) -> list[ObdDeviceSnapshot]:
        return self._scanner.scan_devices(timeout_s=timeout_s)

    def pair_device(self, mac_address: str) -> ObdDeviceSnapshot:
        return self._pairer.pair_device(mac_address)


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
        raise HelperFailure(f"Unsupported command: {args.command}")
    except (ValueError, HelperFailure) as exc:
        _print_json({"error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
