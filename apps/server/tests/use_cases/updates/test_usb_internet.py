from __future__ import annotations

from pathlib import Path

import pytest
from _update_manager_test_helpers import FakeRunner

from vibesensor.use_cases.updates.usb_internet import (
    UsbInternetStatusService,
    _parse_nmcli_device_status,
)


def _make_usb_interface(
    sys_class_net: Path,
    *,
    interface_name: str,
    driver_name: str,
    carrier_on: bool | None = None,
) -> None:
    interface_dir = sys_class_net / interface_name
    interface_dir.mkdir(parents=True)
    device_dir = sys_class_net.parent.parent / "devices" / interface_name / "usb-bus"
    device_dir.mkdir(parents=True)
    driver_dir = sys_class_net.parent.parent / "drivers" / driver_name
    driver_dir.mkdir(parents=True)
    (device_dir / "driver").symlink_to(driver_dir)
    (interface_dir / "device").symlink_to(device_dir)
    if carrier_on is not None:
        (interface_dir / "carrier").write_text("1\n" if carrier_on else "0\n", encoding="utf-8")


class _UsbActivationRunner(FakeRunner):
    def __init__(self) -> None:
        super().__init__()
        self._activation_attempted = False

    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 30,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        self.calls.append((list(args), {"timeout": timeout, "env": env}))
        joined = " ".join(args)
        if "nmcli --wait 15 device up eth0" in joined:
            self._activation_attempted = True
            return (0, "", "")
        if "nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status" in joined:
            if self._activation_attempted:
                return (0, "eth0:ethernet:connected:iPhone USB\n", "")
            return (0, "eth0:ethernet:unavailable:--\n", "")
        if "ip -4 -o addr show dev eth0 scope global" in joined:
            if self._activation_attempted:
                return (
                    0,
                    "2: eth0    inet 172.20.10.2/28 brd 172.20.10.15 scope global eth0\n",
                    "",
                )
            return (0, "", "")
        if "ip -4 route show default dev eth0" in joined:
            if self._activation_attempted:
                return (
                    0,
                    "default via 172.20.10.1 dev eth0 proto dhcp src 172.20.10.2 metric 100\n",
                    "",
                )
            return (0, "", "")
        return self.default_response


class _UsbActivationFailureRunner(FakeRunner):
    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 30,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        self.calls.append((list(args), {"timeout": timeout, "env": env}))
        joined = " ".join(args)
        if "nmcli --wait 15 device up eth0" in joined:
            return (4, "", "Error: Connection activation failed: device not ready")
        if "nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status" in joined:
            return (0, "eth0:ethernet:unavailable:--\n", "")
        if "ip -4 -o addr show dev eth0 scope global" in joined:
            return (0, "", "")
        if "ip -4 route show default dev eth0" in joined:
            return (0, "", "")
        return self.default_response


def test_parse_nmcli_device_status_normalizes_missing_connection_name() -> None:
    statuses = _parse_nmcli_device_status("usb0:ethernet:connected:--\n")

    assert statuses["usb0"].interface_name == "usb0"
    assert statuses["usb0"].device_type == "ethernet"
    assert statuses["usb0"].state == "connected"
    assert statuses["usb0"].connection_name is None


@pytest.mark.asyncio
async def test_usb_internet_snapshot_reports_not_detected_without_usb_interfaces(
    tmp_path: Path,
) -> None:
    sys_class_net = tmp_path / "sys" / "class" / "net"
    sys_class_net.mkdir(parents=True)
    (sys_class_net / "lo").mkdir()
    service = UsbInternetStatusService(runner=FakeRunner(), sys_class_net=sys_class_net)

    snapshot = await service.snapshot()

    assert snapshot.detected is False
    assert snapshot.usable is False
    assert snapshot.interface_name is None
    assert snapshot.diagnostic == "No USB network interface is currently detected."


@pytest.mark.asyncio
async def test_usb_internet_snapshot_prefers_connected_ipheth_interface(tmp_path: Path) -> None:
    sys_class_net = tmp_path / "sys" / "class" / "net"
    sys_class_net.mkdir(parents=True)
    _make_usb_interface(
        sys_class_net,
        interface_name="usb0",
        driver_name="ipheth",
        carrier_on=True,
    )

    runner = FakeRunner()
    runner.set_response(
        "nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status",
        0,
        "usb0:ethernet:connected:iPhone USB\n",
    )
    runner.set_response(
        "ip -4 -o addr show dev usb0 scope global",
        0,
        "2: usb0    inet 172.20.10.2/28 brd 172.20.10.15 scope global usb0\n",
    )
    runner.set_response(
        "ip -4 route show default dev usb0",
        0,
        "default via 172.20.10.1 dev usb0 proto dhcp src 172.20.10.2 metric 100\n",
    )
    service = UsbInternetStatusService(runner=runner, sys_class_net=sys_class_net)

    snapshot = await service.snapshot()

    assert snapshot.detected is True
    assert snapshot.usable is True
    assert snapshot.interface_name == "usb0"
    assert snapshot.connection_name == "iPhone USB"
    assert snapshot.driver == "ipheth"
    assert snapshot.ipv4_addresses == ("172.20.10.2/28",)
    assert snapshot.gateway == "172.20.10.1"
    assert snapshot.has_default_route is True
    assert snapshot.diagnostic == "USB internet is ready on 'usb0'."


@pytest.mark.asyncio
async def test_usb_internet_snapshot_can_activate_detected_but_unavailable_interface(
    tmp_path: Path,
) -> None:
    sys_class_net = tmp_path / "sys" / "class" / "net"
    sys_class_net.mkdir(parents=True)
    _make_usb_interface(
        sys_class_net,
        interface_name="eth0",
        driver_name="ipheth",
        carrier_on=True,
    )

    service = UsbInternetStatusService(
        runner=_UsbActivationRunner(),
        sys_class_net=sys_class_net,
    )

    snapshot = await service.snapshot(activate=True)

    assert snapshot.detected is True
    assert snapshot.usable is True
    assert snapshot.interface_name == "eth0"
    assert snapshot.connection_name == "iPhone USB"
    assert snapshot.driver == "ipheth"
    assert snapshot.ipv4_addresses == ("172.20.10.2/28",)
    assert snapshot.gateway == "172.20.10.1"
    assert snapshot.has_default_route is True
    assert snapshot.diagnostic == "USB internet is ready on 'eth0'."


@pytest.mark.asyncio
async def test_usb_internet_snapshot_reports_activation_failure_in_diagnostic(
    tmp_path: Path,
) -> None:
    sys_class_net = tmp_path / "sys" / "class" / "net"
    sys_class_net.mkdir(parents=True)
    _make_usb_interface(
        sys_class_net,
        interface_name="eth0",
        driver_name="ipheth",
        carrier_on=True,
    )

    service = UsbInternetStatusService(
        runner=_UsbActivationFailureRunner(),
        sys_class_net=sys_class_net,
    )

    snapshot = await service.snapshot(activate=True)

    assert snapshot.detected is True
    assert snapshot.usable is False
    assert snapshot.interface_name == "eth0"
    assert snapshot.driver == "ipheth"
    assert snapshot.has_default_route is False
    assert (
        snapshot.diagnostic
        == "USB interface 'eth0' is detected, but NetworkManager reports state 'unavailable'. "
        "Auto-activation failed (Error: Connection activation failed: device not ready)."
    )


@pytest.mark.asyncio
async def test_usb_internet_snapshot_reports_no_carrier_hint_without_activation(
    tmp_path: Path,
) -> None:
    sys_class_net = tmp_path / "sys" / "class" / "net"
    sys_class_net.mkdir(parents=True)
    _make_usb_interface(
        sys_class_net,
        interface_name="eth0",
        driver_name="ipheth",
        carrier_on=False,
    )

    runner = FakeRunner()
    runner.set_response(
        "nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status",
        0,
        "eth0:ethernet:unavailable:--\n",
    )
    runner.set_response("ip -4 -o addr show dev eth0 scope global", 0, "")
    runner.set_response("ip -4 route show default dev eth0", 0, "")
    service = UsbInternetStatusService(runner=runner, sys_class_net=sys_class_net)

    snapshot = await service.snapshot(activate=True)

    assert snapshot.detected is True
    assert snapshot.usable is False
    assert snapshot.interface_name == "eth0"
    assert (
        snapshot.diagnostic
        == "USB interface 'eth0' is detected, but link carrier is off. "
        "Enable USB tethering/personal hotspot and trust this Pi on the phone."
    )
    assert not any("device up eth0" in " ".join(call[0]) for call in runner.calls)
