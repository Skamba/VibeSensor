from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vibesensor.use_cases.updates.models import UpdatePhase, UsbInternetStatus
from vibesensor.use_cases.updates.runner import CommandRunner, UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wifi.wifi_config import UpdateWifiConfig
from vibesensor.use_cases.updates.wifi.wifi_readiness import UpdateWifiReadiness

_SYS_CLASS_NET = Path("/sys/class/net")
_USB_NETWORK_DRIVERS = frozenset({"cdc_ether", "cdc_ncm", "ipheth", "rndis_host"})


@dataclass(frozen=True, slots=True)
class _NmcliDeviceStatus:
    interface_name: str
    device_type: str
    state: str
    connection_name: str | None


@dataclass(frozen=True, slots=True)
class _UsbCandidateStatus:
    interface_name: str
    state: str
    connection_name: str | None
    driver: str | None
    ipv4_addresses: tuple[str, ...]
    gateway: str | None
    has_default_route: bool
    diagnostic: str

    @property
    def usable(self) -> bool:
        return self.state == "connected" and bool(self.ipv4_addresses) and self.has_default_route


def _safe_resolve(path: Path) -> Path | None:
    try:
        return path.resolve()
    except OSError:
        return None


def _driver_name(interface_name: str, *, sys_class_net: Path = _SYS_CLASS_NET) -> str | None:
    driver_link = sys_class_net / interface_name / "device" / "driver"
    resolved = _safe_resolve(driver_link)
    return resolved.name if resolved is not None else None


def _is_usb_backed_interface(interface_name: str, *, sys_class_net: Path = _SYS_CLASS_NET) -> bool:
    device_dir = sys_class_net / interface_name / "device"
    resolved = _safe_resolve(device_dir)
    if resolved is None:
        return False
    resolved_text = str(resolved)
    if "/usb" in resolved_text:
        return True
    driver = _driver_name(interface_name, sys_class_net=sys_class_net)
    return driver in _USB_NETWORK_DRIVERS


def _candidate_interfaces(*, sys_class_net: Path = _SYS_CLASS_NET) -> tuple[str, ...]:
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


def _parse_nmcli_device_status(stdout: str) -> dict[str, _NmcliDeviceStatus]:
    statuses: dict[str, _NmcliDeviceStatus] = {}
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
        statuses[interface_name] = _NmcliDeviceStatus(
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


def _candidate_rank(candidate: _UsbCandidateStatus) -> tuple[int, int, int]:
    return (
        2 if candidate.usable else 0,
        1 if candidate.state == "connected" else 0,
        1 if candidate.driver == "ipheth" else 0,
    )


def _candidate_diagnostic(
    interface_name: str,
    *,
    state: str,
    nmcli_error: str,
    addr_error: str,
    route_error: str,
    ipv4_addresses: tuple[str, ...],
    has_default_route: bool,
) -> str:
    if nmcli_error:
        return f"Could not query NetworkManager device status ({nmcli_error})."
    if state != "connected":
        return (
            f"USB interface '{interface_name}' is detected, but NetworkManager reports "
            f"state '{state or 'unknown'}'."
        )
    if addr_error:
        return (
            f"USB interface '{interface_name}' is connected, but IPv4 status "
            f"could not be read ({addr_error})."
        )
    if not ipv4_addresses:
        return (
            f"USB interface '{interface_name}' is connected, but no IPv4 address is assigned yet."
        )
    if route_error:
        return (
            f"USB interface '{interface_name}' is connected, but route status "
            f"could not be read ({route_error})."
        )
    if not has_default_route:
        return (
            f"USB interface '{interface_name}' is connected, but no default IPv4 route is active."
        )
    return f"USB internet is ready on '{interface_name}'."


class UsbInternetStatusService:
    """Inspect live Linux/NM state to determine whether USB internet is available."""

    __slots__ = ("_runner", "_sys_class_net")

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        sys_class_net: Path = _SYS_CLASS_NET,
    ) -> None:
        self._runner = runner or CommandRunner()
        self._sys_class_net = sys_class_net

    async def snapshot(self) -> UsbInternetStatus:
        candidates = _candidate_interfaces(sys_class_net=self._sys_class_net)
        if not candidates:
            return UsbInternetStatus(
                detected=False,
                usable=False,
                diagnostic="No USB network interface is currently detected.",
            )

        nmcli_error = ""
        rc, stdout, stderr = await self._runner.run(
            ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"],
            timeout=10,
        )
        device_status = _parse_nmcli_device_status(stdout) if rc == 0 else {}
        if rc != 0:
            nmcli_error = (stderr or stdout or f"exit {rc}").strip()

        candidate_statuses: list[_UsbCandidateStatus] = []
        for interface_name in candidates:
            row = device_status.get(interface_name)
            state = row.state if row is not None else "unknown"
            connection_name = row.connection_name if row is not None else None
            driver = _driver_name(interface_name, sys_class_net=self._sys_class_net)

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

            candidate_statuses.append(
                _UsbCandidateStatus(
                    interface_name=interface_name,
                    state=state,
                    connection_name=connection_name,
                    driver=driver,
                    ipv4_addresses=ipv4_addresses,
                    gateway=gateway,
                    has_default_route=has_default_route,
                    diagnostic=_candidate_diagnostic(
                        interface_name,
                        state=state,
                        nmcli_error=nmcli_error,
                        addr_error=addr_error,
                        route_error=route_error,
                        ipv4_addresses=ipv4_addresses,
                        has_default_route=has_default_route,
                    ),
                ),
            )

        best = max(candidate_statuses, key=_candidate_rank)
        return UsbInternetStatus(
            detected=True,
            usable=best.usable,
            interface_name=best.interface_name,
            connection_name=best.connection_name,
            driver=best.driver,
            ipv4_addresses=best.ipv4_addresses,
            gateway=best.gateway,
            has_default_route=best.has_default_route,
            diagnostic=best.diagnostic,
        )


class UpdateUsbInternetOrchestrator:
    """Validate and reuse an already-present USB internet uplink for updates."""

    __slots__ = ("_readiness", "_status_service", "_tracker")

    def __init__(
        self,
        *,
        status_service: UsbInternetStatusService,
        commands: UpdateCommandExecutor,
        tracker: UpdateStatusTracker,
        config: UpdateWifiConfig,
    ) -> None:
        self._status_service = status_service
        self._tracker = tracker
        self._readiness = UpdateWifiReadiness(
            commands=commands,
            tracker=tracker,
            config=config,
        )

    async def ensure_uplink_ready(self) -> bool:
        status = await self._status_service.snapshot()
        if not status.detected:
            self._tracker.fail(
                UpdatePhase.connecting_usb_internet,
                "USB internet not detected",
                status.diagnostic,
            )
            return False
        if not status.usable:
            self._tracker.fail(
                UpdatePhase.connecting_usb_internet,
                "USB internet detected but not usable",
                status.diagnostic,
            )
            return False
        self._tracker.set_uplink_interface(status.interface_name)
        if status.connection_name:
            self._tracker.log(
                f"Using existing USB internet connection '{status.connection_name}' on "
                f"{status.interface_name}",
            )
        else:
            self._tracker.log(f"Using existing USB internet on {status.interface_name}")
        return await self._readiness.wait_for_dns_ready(
            phase=UpdatePhase.connecting_usb_internet,
            readiness_subject="USB internet",
            failure_message="USB internet detected, but internet/DNS is not ready",
        )
