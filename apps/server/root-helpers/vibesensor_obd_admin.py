#!/usr/bin/python3 -I
"""Root-side Bluetooth OBD admin wrapper (scan, pair, info).

``vibesensor_privileged_helper.py`` runs this as root for "obd" requests from
the server. It is the security boundary for those requests: it accepts only
the three subcommands below with a validated MAC address, and only runs
``rfkill``, ``systemctl start bluetooth``, ``bluetoothctl`` and ``sdptool``.
It prints one JSON object; ``vibesensor/speed/obd/admin_client.py`` parses it.

It runs as root under the system ``python3 -I`` from the root-owned helper
directory (``install_systemd_units.sh``), so it must stay stdlib-only and must
never import ``vibesensor`` or anything else from the service user's venv.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace

CommandRunner = Callable[[list[str], int, bool], tuple[int, str, str]]

# Unblocking a soft-blocked adapter makes BlueZ power it on by itself; a
# ``power on`` racing that answers org.bluez.Error.Busy. Wait for it instead.
# admin_client.py adds this wait to its request timeouts; keep them in sync.
_POWER_ON_BUSY = "org.bluez.Error.Busy"
POWER_ON_WAIT_S = 10
_POWER_ON_POLL_S = 0.5
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


class HelperFailure(RuntimeError):
    """Raised when a privileged Bluetooth helper action fails."""


@dataclass(frozen=True, slots=True)
class Device:
    """One adapter; the fields match ``vibesensor.speed.obd.models.ObdDeviceSnapshot``."""

    mac_address: str
    name: str | None
    paired: bool
    trusted: bool
    connected: bool
    rfcomm_channel: int | None


def normalize_mac(value: str) -> str:
    """Return *value* as 12 lowercase hex chars (copy of ``normalize_sensor_id``)."""
    compact = value.replace(":", "").strip().lower()
    if len(compact) != 12:
        raise ValueError("sensor_id must be 12 hex chars")
    bytes.fromhex(compact)
    return compact


def bluetooth_mac(value: str) -> str:
    """Return *value* as an upper-case colon-separated Bluetooth MAC."""
    normalized = normalize_mac(value)
    return ":".join(normalized[i : i + 2].upper() for i in range(0, 12, 2))


# -- bluetoothctl / sdptool output parsing -----------------------------------


def _clean_name(raw: str | None) -> str | None:
    if raw is None:
        return None
    return raw.strip() or None


def looks_like_mac_alias(raw: str | None) -> bool:
    value = _clean_name(raw)
    if value is None:
        return False
    compact = value.replace(":", "").replace("-", "")
    if len(compact) != 12:
        return False
    try:
        bytes.fromhex(compact)
    except ValueError:
        return False
    return True


def _has_human_name(raw: str | None) -> bool:
    value = _clean_name(raw)
    return value is not None and not looks_like_mac_alias(value)


def preferred_name(*candidates: str | None) -> str | None:
    cleaned = [value for value in (_clean_name(c) for c in candidates) if value]
    for candidate in cleaned:
        if not looks_like_mac_alias(candidate):
            return candidate
    return cleaned[0] if cleaned else None


def _device_line(mac: str, name_parts: list[str]) -> Device:
    return Device(
        mac_address=mac,
        name=_clean_name(" ".join(name_parts)),
        paired=False,
        trusted=False,
        connected=False,
        rfcomm_channel=None,
    )


def parse_devices(output: str, *, scan_events: bool = False) -> list[Device]:
    """Parse ``bluetoothctl devices`` output, or ``scan on`` output with *scan_events*."""
    devices: dict[str, Device] = {}
    for raw_line in output.splitlines():
        line = _ANSI_ESCAPE_RE.sub("", raw_line).strip()
        if scan_events and line.startswith("[NEW] Device "):
            line = line.removeprefix("[NEW] ").strip()
        elif not line.startswith("Device "):
            continue
        _, raw_mac, *name_parts = line.split()
        try:
            mac = normalize_mac(raw_mac)
        except ValueError:
            continue
        devices[mac] = _device_line(mac, name_parts)
    return list(devices.values())


def parse_device_info(output: str, mac_address: str) -> Device:
    """Parse ``bluetoothctl info`` output."""
    names: dict[str, str | None] = {"Name": None, "LocalName": None, "Alias": None}
    flags = {"Paired": False, "Trusted": False, "Connected": False}
    for raw_line in output.splitlines():
        key, sep, value = raw_line.strip().partition(":")
        if not sep:
            continue
        if key in names:
            names[key] = _clean_name(value) or names[key]
        elif key in flags:
            flags[key] = value.strip().lower() == "yes"
    return Device(
        mac_address=normalize_mac(mac_address),
        name=preferred_name(names["Name"], names["LocalName"], names["Alias"]),
        paired=flags["Paired"],
        trusted=flags["Trusted"],
        connected=flags["Connected"],
        rfcomm_channel=None,
    )


def parse_rfcomm_channel(output: str) -> int | None:
    """Return the first advertised RFCOMM channel from ``sdptool browse`` output."""
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.lower().startswith("channel:"):
            continue
        try:
            return int(line.partition(":")[2].strip())
        except ValueError:
            return None
    return None


# -- command execution --------------------------------------------------------


def _text(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else raw


def run_command(argv: list[str], timeout_s: int, allow_timeout: bool) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            argv, check=False, text=True, capture_output=True, timeout=timeout_s
        )
    except FileNotFoundError as exc:
        raise HelperFailure(f"Required command is unavailable: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        if not allow_timeout:
            raise HelperFailure(f"Command timed out after {timeout_s}s: {' '.join(argv)}") from exc
        return 124, _text(exc.stdout).strip(), _text(exc.stderr).strip()
    return int(completed.returncode), completed.stdout.strip(), completed.stderr.strip()


class BluetoothAdmin:
    """Scan for, pair, and inspect Bluetooth OBD adapters."""

    __slots__ = ("_monotonic", "_runner", "_sleep")

    def __init__(
        self,
        *,
        runner: CommandRunner = run_command,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._runner = runner
        self._sleep = sleep
        self._monotonic = monotonic

    def run(self, argv: list[str], *, timeout_s: int, allow_timeout: bool = False) -> str:
        returncode, stdout, stderr = self._runner(argv, timeout_s, allow_timeout)
        if returncode not in (0, 124):
            raise HelperFailure(stderr or stdout or f"Command failed: {' '.join(argv)}")
        return stdout or stderr

    def bluetoothctl(self, *args: str, timeout_s: int, ignore_errors: bool = False) -> str:
        try:
            return self.run(["bluetoothctl", *args], timeout_s=timeout_s)
        except HelperFailure:
            if ignore_errors:
                return ""
            raise

    def prepare_controller(self) -> None:
        self.run(["rfkill", "unblock", "bluetooth"], timeout_s=5)
        self.run(["systemctl", "start", "bluetooth"], timeout_s=10)
        try:
            self.bluetoothctl("power", "on", timeout_s=10)
        except HelperFailure as exc:
            if _POWER_ON_BUSY not in str(exc):
                raise
            self._wait_until_powered(exc)

    def _wait_until_powered(self, busy: HelperFailure) -> None:
        """Poll the adapter BlueZ is already powering on; re-raise *busy* if it never is."""
        deadline = self._monotonic() + POWER_ON_WAIT_S
        while True:
            self._sleep(_POWER_ON_POLL_S)
            show = self.bluetoothctl("show", timeout_s=5, ignore_errors=True)
            if any(line.strip() == "Powered: yes" for line in show.splitlines()):
                return
            if self._monotonic() >= deadline:
                raise busy

    def device_info(
        self, mac_address: str, *, ensure_ready: bool = True, resolve_rfcomm: bool = True
    ) -> Device:
        normalized = normalize_mac(mac_address)
        if ensure_ready:
            self.prepare_controller()
        bt_mac = bluetooth_mac(normalized)
        info_output = self.bluetoothctl("info", bt_mac, timeout_s=8, ignore_errors=True)
        device = parse_device_info(info_output, normalized)
        if not resolve_rfcomm:
            return device
        try:
            channel_output = self.run(["sdptool", "browse", bt_mac], timeout_s=10)
        except HelperFailure:
            return device
        return replace(device, rfcomm_channel=parse_rfcomm_channel(channel_output))

    def _listed_devices(self, *args: str) -> list[Device]:
        return parse_devices(self.bluetoothctl(*args, timeout_s=5, ignore_errors=True))

    def scan_devices(self, *, timeout_s: int) -> list[Device]:
        self.prepare_controller()
        scan_timeout_s = max(3, int(timeout_s))
        scan_output = self.run(
            ["bluetoothctl", "--timeout", str(scan_timeout_s), "scan", "on"],
            timeout_s=scan_timeout_s + 2,
        )
        try:
            devices = {d.mac_address: d for d in parse_devices(scan_output, scan_events=True)}
            devices.update({d.mac_address: d for d in self._listed_devices("devices")})
            paired = {d.mac_address for d in self._listed_devices("devices", "Paired")}
            paired.update(d.mac_address for d in self._listed_devices("paired-devices"))
        finally:
            self.bluetoothctl("scan", "off", timeout_s=5, ignore_errors=True)
        resolved: list[Device] = []
        for device in devices.values():
            is_paired = device.mac_address in paired
            if not (is_paired or device.name is None or looks_like_mac_alias(device.name)):
                resolved.append(device)
                continue
            try:
                detailed = self.device_info(
                    device.mac_address, ensure_ready=False, resolve_rfcomm=False
                )
            except HelperFailure:
                resolved.append(replace(device, paired=is_paired))
                continue
            resolved.append(
                replace(
                    detailed,
                    name=preferred_name(detailed.name, device.name),
                    paired=detailed.paired or is_paired,
                )
            )
        return sorted(
            resolved,
            key=lambda d: (
                not d.connected,
                not d.paired,
                not _has_human_name(d.name),
                (d.name or d.mac_address).lower(),
            ),
        )

    def pair_device(self, mac_address: str) -> Device:
        normalized = normalize_mac(mac_address)
        self.prepare_controller()
        bt_mac = bluetooth_mac(normalized)
        self.bluetoothctl("agent", "on", timeout_s=5, ignore_errors=True)
        self.bluetoothctl("default-agent", timeout_s=5, ignore_errors=True)
        self.bluetoothctl("pair", bt_mac, timeout_s=25, ignore_errors=True)
        self.bluetoothctl("trust", bt_mac, timeout_s=10, ignore_errors=True)
        self.bluetoothctl("connect", bt_mac, timeout_s=15, ignore_errors=True)
        device = self.device_info(normalized, ensure_ready=False)
        if not device.paired:
            raise HelperFailure("Bluetooth OBD pairing did not complete successfully")
        if not device.trusted:
            raise HelperFailure("Bluetooth OBD adapter paired, but trust setup failed")
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


def main(argv: Sequence[str] | None = None, *, admin: BluetoothAdmin | None = None) -> int:
    args = _build_parser().parse_args(argv)
    admin = BluetoothAdmin() if admin is None else admin
    try:
        if args.command == "scan":
            scan_timeout_s = max(3, int(args.timeout))
            devices = admin.scan_devices(timeout_s=scan_timeout_s)
            payload: dict[str, object] = {
                "devices": [asdict(device) for device in devices],
                "scan_timeout_s": scan_timeout_s,
            }
        elif args.command == "pair":
            payload = {"device": asdict(admin.pair_device(args.mac_address))}
        else:
            payload = {"device": asdict(admin.device_info(args.mac_address))}
    except (ValueError, HelperFailure) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
