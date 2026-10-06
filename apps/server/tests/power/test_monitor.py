"""PowerMonitor against a fake sysfs: transitions, run issues, and per-boot memory."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from test_support.power import FakePiSysfs

from vibesensor.power.monitor import PowerMonitor


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def sysfs(tmp_path: Path) -> FakePiSysfs:
    return FakePiSysfs(tmp_path / "sys")


def _monitor(
    sysfs: FakePiSysfs,
    clock: _Clock,
    *,
    state_path: Path | None = None,
    boot_id: str = "boot-1",
) -> PowerMonitor:
    return PowerMonitor(
        state_path=state_path,
        hwmon_dir=sysfs.hwmon,
        thermal_path=sysfs.thermal,
        monotonic=clock,
        boot_id=lambda: boot_id,
    )


def _events(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    return [(record.levelno, getattr(record, "event", "")) for record in caplog.records]


def test_a_supply_dip_is_logged_once_flagged_for_the_run_and_remembered(
    sysfs: FakePiSysfs, caplog: pytest.LogCaptureFixture
) -> None:
    clock = _Clock()
    monitor = _monitor(sysfs, clock)
    caplog.set_level(logging.INFO, logger="vibesensor.power.monitor")

    monitor.poll()
    run_start = clock.now = 110.0
    sysfs.set(undervoltage=True, celsius=45.0)
    for clock.now in (111.0, 112.0, 113.0):
        monitor.poll()
    assert monitor.snapshot()["undervoltage_now"] is True
    sysfs.set(undervoltage=False, celsius=45.0)
    clock.now = 114.0
    monitor.poll()

    assert _events(caplog) == [
        (logging.WARNING, "power_undervoltage"),
        (logging.INFO, "power_undervoltage_cleared"),
    ]
    assert monitor.snapshot() == {
        "undervoltage_now": False,
        "undervoltage_seen": True,
        "temperature_c": 45.0,
        "temperature_state": "normal",
        "hottest_state_seen": "normal",
    }
    assert monitor.issues_since(run_start) == ("undervoltage",)
    # A run that started after the dip ended is clean.
    assert monitor.issues_since(114.5) == ()


def test_temperature_states_follow_the_pi_limits_with_hysteresis(
    sysfs: FakePiSysfs, caplog: pytest.LogCaptureFixture
) -> None:
    clock = _Clock()
    monitor = _monitor(sysfs, clock)
    caplog.set_level(logging.INFO, logger="vibesensor.power.monitor")
    states = []
    for celsius in (59.9, 60.0, 58.0, 56.9, 81.0, 78.0, 76.5, 50.0):
        clock.now += 1.0
        sysfs.set(undervoltage=False, celsius=celsius)
        monitor.poll()
        states.append(monitor.snapshot()["temperature_state"])

    assert states == ["normal", "warm", "warm", "normal", "hot", "hot", "warm", "normal"]
    levels = [level for level, event in _events(caplog) if event == "power_temperature"]
    assert levels == [
        logging.WARNING,  # warm
        logging.INFO,  # normal
        logging.WARNING,  # hot
        logging.INFO,  # warm
        logging.INFO,  # normal
    ]
    assert monitor.snapshot()["hottest_state_seen"] == "hot"
    # Only "hot" (throttled) marks a run; the 60 °C soft limit does not.
    assert monitor.issues_since(0.0) == ("overheated",)
    assert monitor.issues_since(clock.now - 1.5) == ()


def test_what_this_boot_has_seen_survives_a_server_restart_but_not_a_reboot(
    sysfs: FakePiSysfs, tmp_path: Path
) -> None:
    state_path = tmp_path / "power_state.json"
    clock = _Clock()
    first = _monitor(sysfs, clock, state_path=state_path)
    sysfs.set(undervoltage=True, celsius=82.0)
    first.poll()
    sysfs.set(undervoltage=False, celsius=40.0)

    restarted = _monitor(sysfs, clock, state_path=state_path)
    restarted.poll()
    rebooted = _monitor(sysfs, clock, state_path=state_path, boot_id="boot-2")
    rebooted.poll()

    seen = {
        name: (monitor.snapshot()["undervoltage_seen"], monitor.snapshot()["hottest_state_seen"])
        for name, monitor in (("restarted", restarted), ("rebooted", rebooted))
    }
    assert seen == {"restarted": (True, "hot"), "rebooted": (False, "normal")}
    # A restart remembers what was seen, not when: earlier runs are not re-flagged.
    assert restarted.issues_since(0.0) == ()


def test_off_a_pi_nothing_is_read_or_flagged(tmp_path: Path) -> None:
    monitor = PowerMonitor(hwmon_dir=tmp_path / "none", thermal_path=tmp_path / "none" / "temp")
    monitor.poll()

    assert monitor.snapshot() == {
        "undervoltage_now": None,
        "undervoltage_seen": False,
        "temperature_c": None,
        "temperature_state": "unknown",
        "hottest_state_seen": "unknown",
    }
    assert monitor.issues_since(0.0) == ()
