from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vibesensor.use_cases.updates.runner import CommandRunner

DEFAULT_SYS_CLASS_NET = Path("/sys/class/net")
_USB_NETWORK_DRIVERS = frozenset({"cdc_ether", "cdc_ncm", "ipheth", "rndis_host"})

__all__ = [
    "DEFAULT_SYS_CLASS_NET",
    "NmcliDeviceStatus",
    "UsbCandidateObservation",
    "UsbInternetStatusInspector",
    "parse_nmcli_device_status",
]


@dataclass(frozen=True, slots=True)
class NmcliDeviceStatus:
    interface_name: str
    device_type: str
    state: str
    connection_name: str | None


@dataclass(frozen=True, slots=True)
class UsbCandidateObservation:
    interface_name: str
    state: str
    connection_name: str | None
    driver: str | None
    carrier_on: bool | None
    ipv4_addresses: tuple[str, ...]
    gateway: str | None
    has_default_route: bool
    nmcli_error: str
    addr_error: str
    route_error: str

    @property
    def usable(self) -> bool:
        return self.state == "connected" and bool(self.ipv4_addresses) and self.has_default_route


def _safe_resolve(path: Path) -> Path | None:
    try:
        return path.resolve()
    except OSError:
        return None


def _driver_name(interface_name: str, *, sys_class_net: Path = DEFAULT_SYS_CLASS_NET) -> str | None:
    driver_link = sys_class_net / interface_name / "device" / "driver"
    resolved = _safe_resolve(driver_link)
    return resolved.name if resolved is not None else None


def _carrier_on(interface_name: str, *, sys_class_net: Path = DEFAULT_SYS_CLASS_NET) -> bool | None:
    carrier_path = sys_class_net / interface_name / "carrier"
    try:
        raw_value = carrier_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if raw_value == "1":
        return True
    if raw_value == "0":
        return False
    return None


def _is_usb_backed_interface(
    interface_name: str,
    *,
    sys_class_net: Path = DEFAULT_SYS_CLASS_NET,
) -> bool:
    device_dir = sys_class_net / interface_name / "device"
    resolved = _safe_resolve(device_dir)
    if resolved is None:
        return False
    if "/usb" in str(resolved):
        return True
    driver = _driver_name(interface_name, sys_class_net=sys_class_net)
    return driver in _USB_NETWORK_DRIVERS


def _candidate_interfaces(*, sys_class_net: Path = DEFAULT_SYS_CLASS_NET) -> tuple[str, ...]:
    if not sys_class_net.is_dir():
        return ()
    candidates = [
        entry.name
        for entry in sorted(sys_class_net.iterdir(), key=lambda item: item.name)
        if (
            entry.is_dir()
            and entry.name != "lo"
            and _is_usb_backed_interface(entry.name, sys_class_net=sys_class_net)
        )
    ]
    return tuple(candidates)


def parse_nmcli_device_status(stdout: str) -> dict[str, NmcliDeviceStatus]:
    statuses: dict[str, NmcliDeviceStatus] = {}
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(":", 3)
        if len(parts) != 4:
            continue
        interface_name, device_type, state, connection_name = parts
        normalized_connection = (
            connection_name if connection_name and connection_name != "--" else None
        )
        statuses[interface_name] = NmcliDeviceStatus(
            interface_name=interface_name,
            device_type=device_type,
            state=state,
            connection_name=normalized_connection,
        )
    return statuses


def _parse_ipv4_addresses(stdout: str) -> tuple[str, ...]:
    addresses: list[str] = []
    for raw_line in stdout.splitlines():
        parts = raw_line.split()
        if "inet" not in parts:
            continue
        try:
            inet_index = parts.index("inet")
        except ValueError:
            continue
        address_index = inet_index + 1
        if address_index < len(parts):
            addresses.append(parts[address_index])
    return tuple(addresses)


def _parse_default_route(stdout: str) -> tuple[bool, str | None]:
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("default"):
            continue
        parts = line.split()
        gateway: str | None = None
        if "via" in parts:
            via_index = parts.index("via")
            if via_index + 1 < len(parts):
                gateway = parts[via_index + 1]
        return True, gateway
    return False, None


class UsbInternetStatusInspector:
    """Collect raw Linux and NetworkManager observations for USB tethering."""

    __slots__ = ("_runner", "_sys_class_net")

    def __init__(
        self,
        *,
        runner: CommandRunner,
        sys_class_net: Path = DEFAULT_SYS_CLASS_NET,
    ) -> None:
        self._runner = runner
        self._sys_class_net = sys_class_net

    async def collect_candidates(self) -> list[UsbCandidateObservation]:
        candidates = _candidate_interfaces(sys_class_net=self._sys_class_net)
        if not candidates:
            return []

        nmcli_error = ""
        rc, stdout, stderr = await self._runner.run(
            ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"],
            timeout=10,
        )
        device_status = parse_nmcli_device_status(stdout) if rc == 0 else {}
        if rc != 0:
            nmcli_error = (stderr or stdout or f"exit {rc}").strip()

        observations: list[UsbCandidateObservation] = []
        for interface_name in candidates:
            row = device_status.get(interface_name)
            state = row.state if row is not None else "unknown"
            connection_name = row.connection_name if row is not None else None
            driver = _driver_name(interface_name, sys_class_net=self._sys_class_net)
            carrier_on = _carrier_on(interface_name, sys_class_net=self._sys_class_net)

            addr_rc, addr_stdout, addr_stderr = await self._runner.run(
                ["ip", "-4", "-o", "addr", "show", "dev", interface_name, "scope", "global"],
                timeout=10,
            )
            ipv4_addresses = _parse_ipv4_addresses(addr_stdout) if addr_rc == 0 else ()
            addr_error = (
                "" if addr_rc == 0 else (addr_stderr or addr_stdout or f"exit {addr_rc}").strip()
            )

            route_rc, route_stdout, route_stderr = await self._runner.run(
                ["ip", "-4", "route", "show", "default", "dev", interface_name],
                timeout=10,
            )
            has_default_route, gateway = (
                _parse_default_route(route_stdout) if route_rc == 0 else (False, None)
            )
            route_error = (
                ""
                if route_rc == 0
                else (route_stderr or route_stdout or f"exit {route_rc}").strip()
            )

            observations.append(
                UsbCandidateObservation(
                    interface_name=interface_name,
                    state=state,
                    connection_name=connection_name,
                    driver=driver,
                    carrier_on=carrier_on,
                    ipv4_addresses=ipv4_addresses,
                    gateway=gateway,
                    has_default_route=has_default_route,
                    nmcli_error=nmcli_error,
                    addr_error=addr_error,
                    route_error=route_error,
                )
            )

        return observations
