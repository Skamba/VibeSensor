"""Power monitors for tests: one with no sensors, and a fake Pi sysfs."""

from __future__ import annotations

from pathlib import Path

from vibesensor.power.monitor import PowerMonitor, PowerSnapshot

_MISSING = Path("/nonexistent/vibesensor-test")


def sensorless_power_monitor() -> PowerMonitor:
    """A monitor that reads no host sensor, so tests never see the machine's temperature."""
    return PowerMonitor(hwmon_dir=_MISSING, thermal_path=_MISSING / "temp")


def unknown_power() -> PowerSnapshot:
    return sensorless_power_monitor().snapshot()


class FakePiSysfs:
    """A fake /sys with the Pi's ``cpu_thermal`` and ``rpi_volt`` hwmon devices."""

    def __init__(self, root: Path) -> None:
        self.hwmon = root / "hwmon"
        for index, name in enumerate(("cpu_thermal", "rpi_volt")):
            device = self.hwmon / f"hwmon{index}"
            device.mkdir(parents=True)
            (device / "name").write_text(f"{name}\n")
        self.alarm = self.hwmon / "hwmon1" / "in0_lcrit_alarm"
        self.thermal = root / "thermal_zone0" / "temp"
        self.thermal.parent.mkdir()
        self.set(undervoltage=False, celsius=45.0)

    def set(self, *, undervoltage: bool, celsius: float) -> None:
        self.alarm.write_text(f"{int(undervoltage)}\n")
        self.thermal.write_text(f"{round(celsius * 1000)}\n")
