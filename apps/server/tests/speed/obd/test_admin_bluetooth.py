"""Controller preparation survives BlueZ powering the adapter on by itself."""

from __future__ import annotations

import pytest

from vibesensor.speed.obd.admin_bluetooth import (
    POWER_ON_WAIT_S,
    BluetoothAdminSession,
    HelperFailure,
)

_BUSY = "Failed to set power on: org.bluez.Error.Busy"


class _FakeBluez:
    """Answer ``power on`` with *power_on_error* and report Powered after *powered_after_s*."""

    def __init__(self, *, power_on_error: str | None, powered_after_s: float | None) -> None:
        self.power_on_error = power_on_error
        self.powered_after_s = powered_after_s
        self.now = 0.0
        self.calls: list[tuple[str, ...]] = []

    def runner(self, argv: list[str], timeout_s: int, allow_timeout: bool) -> tuple[int, str, str]:
        del timeout_s, allow_timeout
        self.calls.append(tuple(argv))
        if argv == ["bluetoothctl", "power", "on"] and self.power_on_error is not None:
            return 1, "", self.power_on_error
        if argv == ["bluetoothctl", "show"]:
            powered = self.powered_after_s is not None and self.now >= self.powered_after_s
            return 0, f"Controller B8:27:EB:00:00:01\n\tPowered: {'yes' if powered else 'no'}\n", ""
        return 0, "", ""

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def session(self) -> BluetoothAdminSession:
        return BluetoothAdminSession(
            runner=self.runner, sleep=self.sleep, monotonic=lambda: self.now
        )


def test_busy_power_on_waits_for_the_adapter_bluez_is_already_powering() -> None:
    bluez = _FakeBluez(power_on_error=_BUSY, powered_after_s=2.0)

    bluez.session().prepare_controller()

    assert bluez.calls[:3] == [
        ("rfkill", "unblock", "bluetooth"),
        ("systemctl", "start", "bluetooth"),
        ("bluetoothctl", "power", "on"),
    ]
    assert 2.0 <= bluez.now < POWER_ON_WAIT_S


def test_busy_power_on_fails_with_busy_when_the_adapter_never_powers() -> None:
    bluez = _FakeBluez(power_on_error=_BUSY, powered_after_s=None)

    with pytest.raises(HelperFailure, match=r"org\.bluez\.Error\.Busy"):
        bluez.session().prepare_controller()

    assert POWER_ON_WAIT_S <= bluez.now < POWER_ON_WAIT_S + 1


def test_other_power_on_failures_are_not_waited_out() -> None:
    bluez = _FakeBluez(power_on_error="No default controller available", powered_after_s=0.0)

    with pytest.raises(HelperFailure, match="No default controller"):
        bluez.session().prepare_controller()

    assert ("bluetoothctl", "show") not in bluez.calls
    assert bluez.now == 0.0
