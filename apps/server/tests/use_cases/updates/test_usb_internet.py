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
) -> None:
    interface_dir = sys_class_net / interface_name
    interface_dir.mkdir(parents=True)
    device_dir = sys_class_net.parent.parent / "devices" / interface_name / "usb-bus"
    device_dir.mkdir(parents=True)
    driver_dir = sys_class_net.parent.parent / "drivers" / driver_name
    driver_dir.mkdir(parents=True)
    (device_dir / "driver").symlink_to(driver_dir)
    (interface_dir / "device").symlink_to(device_dir)


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
    _make_usb_interface(sys_class_net, interface_name="usb0", driver_name="ipheth")

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
